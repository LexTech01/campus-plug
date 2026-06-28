import os
import re
import secrets
import random
import time
from io import BytesIO
from datetime import datetime, timedelta
from sqlalchemy.exc import IntegrityError
from markupsafe import escape
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, Listing, Gig, Notification, UNIVERSITIES, MOMO_PROVIDERS, generate_referral_code
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from PIL import Image
from mail import send_email
from utils import rate_limit

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.route('/register', methods=['GET', 'POST'])
@rate_limit('register', max_attempts=5, window=60)
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    errors = {}
    form_data = {}
    
    # Pre-fill referral code from ?ref= query param
    ref_from_url = request.args.get('ref', '').strip().upper()
    if ref_from_url:
        form_data['referral_code'] = ref_from_url
    
    if request.method == 'POST':
        # Retrieve form data
        email = request.form.get('email', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        university = request.form.get('university', '')
        phone = request.form.get('phone', '').strip()
        momo_provider = request.form.get('momo_provider', '')
        bio = request.form.get('bio', '').strip()[:500]
        account_type = request.form.get('account_type', 'regular')
        referral_code_input = request.form.get('referral_code', '').strip().upper()[:8]
        
        # Save submitted options to repopulate the form
        form_data = {
            'email': email,
            'full_name': full_name,
            'university': university,
            'phone': phone,
            'momo_provider': momo_provider,
            'bio': bio,
            'account_type': account_type,
            'referral_code': referral_code_input
        }
        
        # Backend Validations
        if not email:
            errors['email'] = 'Email is required'
        elif '@' not in email or '.' not in email:
            errors['email'] = 'Please enter a valid email address'
        else:
            existing = User.query.filter_by(email=email).first()
            if existing:
                errors['email'] = 'If this email is valid, it is already registered'
                
        if not full_name:
            errors['full_name'] = 'Full name is required'
            
        if not password:
            errors['password'] = 'Password is required'
        else:
            missing = []
            if len(password) < 8:
                missing.append('8+ characters')
            if not re.search(r'[A-Z]', password):
                missing.append('an uppercase letter')
            if not re.search(r'[a-z]', password):
                missing.append('a lowercase letter')
            if not re.search(r'[0-9]', password):
                missing.append('a digit')
            if not re.search(r'[^a-zA-Z0-9]', password):
                missing.append('a special character')
            if missing:
                errors['password'] = 'Password needs ' + ', '.join(missing)
            
        if password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match'
            
        if university not in UNIVERSITIES:
            errors['university'] = 'Please select a valid university'
            
        if not phone:
            errors['phone'] = 'Phone number is required for payouts'
        elif not re.match(r'^0[0-9]{9}$', phone):
            errors['phone'] = 'Enter a valid Ghana phone number (e.g. 024XXXXXXX)'
            
        if momo_provider and momo_provider not in MOMO_PROVIDERS:
            errors['momo_provider'] = 'Please select a valid Mobile Money provider'

        if account_type not in ('regular', 'seller'):
            errors['account_type'] = 'Please select an account type'
            
        if not errors:
            # Resolve referrer
            referred_by = None
            if referral_code_input:
                referred_by = User.query.filter_by(referral_code=referral_code_input).first()
                if not referred_by:
                    errors['referral_code'] = 'Invalid referral code'
                elif referred_by.id == current_app.config.get('REFERRAL_SELF', True) and False:
                    pass  # handled below
                    
        if not errors:
            # Create User
            new_user = User(
                email=email,
                full_name=full_name,
                university=university,
                phone=phone,
                momo_provider=momo_provider,
                bio=bio,
                account_type=account_type,
                avatar='/static/images/default-avatar.png',
                referral_code=generate_referral_code(),
                referred_by_id=referred_by.id if referred_by else None
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                errors['email'] = 'This email is already registered'
                return render_template('auth/signup.html', errors=errors, form_data=form_data)
            
            login_user(new_user)
            flash('Success! Account created and logged in.', 'success')
            return redirect(url_for('index'))
            
    return render_template('auth/signup.html', errors=errors, form_data=form_data)


def send_recommendations(user):
    """Pick a random active listing + open gig and notify the user (in-app + email)."""
    listing = Listing.query.filter_by(status='active', removed_by_admin=False).order_by(db.func.random()).first()
    gig = Gig.query.filter_by(status='open', removed_by_admin=False).order_by(db.func.random()).first()

    if not listing and not gig:
        return

    if listing:
        notif = Notification(
            user_id=user.id,
            notification_type='recommendation',
            message=f'Check out "{listing.title}" — GHS {listing.price}',
            link=url_for('marketplace.detail', listing_id=listing.id)
        )
        db.session.add(notif)

    if gig:
        notif = Notification(
            user_id=user.id,
            notification_type='recommendation',
            message=f'Freelance gig: "{gig.title}" — GHS {gig.budget}',
            link=url_for('freelance.detail', gig_id=gig.id)
        )
        db.session.add(notif)

    user.last_recommendation_at = datetime.utcnow()
    db.session.commit()

    # Send email with recommendations via Resend
    if user.email:
        try:
            listing_url = url_for('marketplace.detail', listing_id=listing.id, _external=True) if listing else None
            gig_url = url_for('freelance.detail', gig_id=gig.id, _external=True) if gig else None
            html_body = render_template('emails/recommendations.html',
                user=user,
                listing={'title': listing.title, 'description': listing.description, 'price': listing.price, 'url': listing_url} if listing else None,
                gig={'title': gig.title, 'description': gig.description, 'budget': gig.budget, 'url': gig_url} if gig else None,
                browse_url=url_for('index', _external=True),
                settings_url=url_for('auth.settings', _external=True)
            )
            send_email(
                to=user.email,
                subject='Discover on Campus Plug',
                html_body=html_body
            )
        except Exception as e:
            current_app.logger.warning(f"Failed to send recommendation email to {user.email}: {e}")


@auth_bp.route('/login', methods=['GET', 'POST'])
@rate_limit('login', max_attempts=5, window=60)
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    errors = {}
    form_data = {}
    
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        
        form_data = {'email': email}
        
        if not email:
            errors['email'] = 'Email is required'
        if not password:
            errors['password'] = 'Password is required'
            
        if not errors:
            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                if user.is_suspended:
                    errors['general'] = 'Your account has been suspended by an administrator.'
                else:
                    login_user(user, remember=remember)
                    flash(f'Welcome back, {user.full_name}!', 'success')

                    # Send daily recommendations if 24h have passed
                    if not user.last_recommendation_at or datetime.utcnow() - user.last_recommendation_at > timedelta(hours=24):
                        send_recommendations(user)
                    
                    # Check for safe next redirect
                    next_page = request.args.get('next')
                    if not next_page or urlparse(next_page).netloc != '' or urlparse(next_page).scheme != '':
                        next_page = url_for('index')
                    return redirect(next_page)
            else:
                # Security guideline: do not specify which credential failed
                errors['general'] = 'Incorrect email or password. Please try again.'
                
    return render_template('auth/login.html', errors=errors, form_data=form_data)


@auth_bp.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('index'))


@auth_bp.route('/heartbeat')
@login_required
def heartbeat():
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    return ('', 204)


@auth_bp.route('/notifications/<int:notification_id>/read')
@login_required
def read_notification(notification_id):
    from models import Notification
    n = Notification.query.get_or_404(notification_id)
    if n.user_id != current_user.id:
        return redirect(url_for('index')), 403
    n.is_read = True
    db.session.commit()
    return redirect(n.link or url_for('index'))


@auth_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def read_all_notifications():
    from models import Notification
    unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).all()
    for n in unread:
        n.is_read = True
    db.session.commit()
    flash('All notifications marked read.', 'success')
    return redirect(request.referrer or url_for('index'))


@auth_bp.route('/notifications')
@login_required
def notifications():
    page = request.args.get('page', 1, type=int)
    pagination = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=20, error_out=False)
    notifications = pagination.items
    return render_template('auth/notifications.html',
        notifications=notifications,
        pagination=pagination
    )


@auth_bp.route('/upgrade-seller')
@login_required
def upgrade_seller():
    if current_user.account_type == 'admin':
        flash('Admin accounts have full access across the platform.', 'info')
    elif current_user.account_type == 'seller':
        flash('You are already a seller.', 'info')
    else:
        current_user.account_type = 'seller'
        db.session.commit()
        flash('Account upgraded to Seller! You can now create marketplace listings.', 'success')
    return redirect(url_for('auth.settings'))


@auth_bp.route('/referrals')
@login_required
def referrals():
    from models import Transaction, TransactionStatus
    # Stats
    total_referred = User.query.filter_by(referred_by_id=current_user.id).count()
    # Count how many referred users have completed a purchase
    completed_referrals = 0
    referred_users = User.query.filter_by(referred_by_id=current_user.id).all()
    for u in referred_users:
        txns = Transaction.query.filter(
            (Transaction.buyer_id == u.id) | (Transaction.seller_id == u.id),
            Transaction.status == TransactionStatus.released
        ).count()
        if txns > 0:
            completed_referrals += 1
    pending_referrals = total_referred - completed_referrals
    referral_link = url_for('auth.register', _external=True, ref=current_user.referral_code)
    progress_to_next = current_user.completed_referral_count % 5
    return render_template('auth/referrals.html',
        total_referred=total_referred,
        completed_referrals=completed_referrals,
        pending_referrals=pending_referrals,
        fee_waivers=current_user.pending_fee_waivers or 0,
        completed_count=current_user.completed_referral_count or 0,
        progress_to_next=progress_to_next,
        referral_link=referral_link,
        referral_code=current_user.referral_code
    )


@auth_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    errors = {}
    form_data = {
        'full_name': current_user.full_name,
        'university': current_user.university,
        'phone': current_user.phone or '',
        'momo_provider': current_user.momo_provider or '',
        'bio': current_user.bio or '',
        'latitude': current_user.latitude or '',
        'longitude': current_user.longitude or '',
        'location_name': current_user.location_name or '',
    }

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        university = request.form.get('university', '')
        phone = request.form.get('phone', '').strip()
        momo_provider = request.form.get('momo_provider', '')
        bio = request.form.get('bio', '').strip()
        lat_str = request.form.get('latitude', '').strip()
        lng_str = request.form.get('longitude', '').strip()
        location_name = request.form.get('location_name', '').strip()

        form_data.update({
            'full_name': full_name,
            'university': university,
            'phone': phone,
            'momo_provider': momo_provider,
            'bio': bio,
            'latitude': lat_str,
            'longitude': lng_str,
            'location_name': location_name,
        })

        if not full_name:
            errors['full_name'] = 'Full name is required'

        if university and university not in UNIVERSITIES:
            errors['university'] = 'Please select a valid university'

        if phone:
            if not re.match(r'^0[0-9]{9}$', phone):
                errors['phone'] = 'Enter a valid Ghana phone number (e.g. 024XXXXXXX)'

        if momo_provider and momo_provider not in MOMO_PROVIDERS:
            errors['momo_provider'] = 'Please select a valid Mobile Money provider'

        latitude = None
        longitude = None
        if lat_str and lng_str:
            try:
                latitude = float(lat_str)
                longitude = float(lng_str)
                if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                    errors['latitude'] = 'Invalid coordinates'
            except ValueError:
                errors['latitude'] = 'Invalid coordinates'

        if not errors:
            current_user.full_name = full_name
            current_user.university = university
            current_user.phone = phone
            current_user.momo_provider = momo_provider
            current_user.bio = bio
            current_user.latitude = latitude
            current_user.longitude = longitude
            from markupsafe import escape
            current_user.location_name = escape(location_name) if location_name else None

            avatar_file = request.files.get('avatar')
            if avatar_file and avatar_file.filename:
                ext = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else ''
                if ext not in current_app.config['ALLOWED_EXTENSIONS']:
                    errors['avatar'] = 'Allowed file formats: PNG, JPG, JPEG, WEBP'
                else:
                    avatar_file.seek(0, 2)
                    size_bytes = avatar_file.tell()
                    avatar_file.seek(0)
                    if size_bytes > 5 * 1024 * 1024:
                        errors['avatar'] = 'Avatar must be less than 5 MB'
                    else:
                        try:
                            from PIL import Image
                            # Decompression bomb protection
                            Image.MAX_IMAGE_PIXELS = 50_000_000
                            img = Image.open(avatar_file)
                            img.verify()
                            avatar_file.seek(0)
                        except Exception:
                            errors['avatar'] = 'File is not a valid image'

                if 'avatar' not in errors:
                    filename = secure_filename(avatar_file.filename)
                    filename = f"avatar_{current_user.id}_{int(time.time())}_{filename}"
                    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    avatar_file.save(file_path)
                    current_user.avatar = f"/static/uploads/{filename}"

            if not errors:
                db.session.commit()
                flash('Profile updated successfully.', 'success')
                return redirect(url_for('auth.settings'))

    return render_template('auth/settings.html', errors=errors, form_data=form_data)


@auth_bp.route('/user/<int:user_id>')
def user_profile(user_id):
    from models import Review, Listing, Gig, Proposal, get_top_seller_ids
    user = User.query.get_or_404(user_id)
    
    # Check suspension
    if user.is_suspended:
        flash("This user is currently suspended from Campus Plug.", "warning")
        return redirect(url_for('index'))
        
    # Paginate reviews received
    page = request.args.get('page', 1, type=int)
    reviews_pagination = Review.query.filter_by(reviewee_id=user.id).order_by(Review.created_at.desc()).paginate(page=page, per_page=5, error_out=False)
    
    # Active visible listings
    listings = Listing.query.filter_by(seller_id=user.id, removed_by_admin=False).filter(Listing.status != 'deleted').all()
    
    # Gigs posted by user (as client)
    gigs = Gig.query.filter_by(client_id=user.id, removed_by_admin=False).all()
    
    # Gigs the user has won (accepted proposals)
    accepted_proposals = Proposal.query.filter_by(freelancer_id=user.id, status='accepted').all()
    won_gig_ids = [p.gig_id for p in accepted_proposals]
    won_gigs = Gig.query.filter(Gig.id.in_(won_gig_ids), Gig.removed_by_admin == False).all() if won_gig_ids else []
    
    is_top_seller = user.id in get_top_seller_ids(10)
    
    return render_template('auth/profile.html', user=user, reviews_pagination=reviews_pagination, listings=listings, gigs=gigs, won_gigs=won_gigs, is_top_seller=is_top_seller)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@rate_limit('forgot_password', max_attempts=3, window=300)
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    errors = {}
    sent = False

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        if not email:
            errors['email'] = 'Email is required'
        else:
            user = User.query.filter_by(email=email).first()
            if user:
                token = secrets.token_urlsafe(32)
                user.password_reset_token = token
                user.password_reset_expires_at = datetime.utcnow() + timedelta(hours=1)
                db.session.commit()

                try:
                    reset_url = url_for('auth.reset_password', token=token, _external=True)
                    html_body = render_template('emails/forgot_password.html', user=user, reset_url=reset_url)
                    send_email(
                        to=user.email,
                        subject='Reset Your Campus Plug Password',
                        html_body=html_body
                    )
                except Exception as e:
                    current_app.logger.error(f"Failed to send password reset email: {e}")

            sent = True

    return render_template('auth/forgot_password.html', errors=errors, sent=sent)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    user = User.query.filter_by(password_reset_token=token).first()
    if not user or not user.password_reset_expires_at or datetime.utcnow() > user.password_reset_expires_at:
        flash('This reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    errors = {}

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        missing = []
        if len(password) < 8:
            missing.append('8+ characters')
        if not re.search(r'[A-Z]', password):
            missing.append('an uppercase letter')
        if not re.search(r'[a-z]', password):
            missing.append('a lowercase letter')
        if not re.search(r'[0-9]', password):
            missing.append('a digit')
        if not re.search(r'[^a-zA-Z0-9]', password):
            missing.append('a special character')
        if missing:
            errors['password'] = 'Password needs ' + ', '.join(missing)

        if password != confirm:
            errors['confirm_password'] = 'Passwords do not match'

        if not errors:
            user.set_password(password)
            user.password_reset_token = None
            user.password_reset_expires_at = None
            db.session.commit()
            flash('Password reset successfully. Please sign in.', 'success')
            return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', errors=errors, token=token)
