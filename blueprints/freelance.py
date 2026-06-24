from io import BytesIO
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user
from models import db, User, Gig, Proposal, Notification, ShowcasePost, ShowcaseLike, ShowcaseComment, GIG_CATEGORIES, UNIVERSITIES
from datetime import datetime
from PIL import Image

freelance_bp = Blueprint('freelance', __name__)

@freelance_bp.route('/freelance')
def browse():
    page = request.args.get('page', 1, type=int)
    per_page = 15
    
    # Query filters
    search_query = request.args.get('search', '').strip()
    university_filter = request.args.get('university', '').strip()
    category_filter = request.args.get('category', '').strip()
    min_budget = request.args.get('min_budget', type=float)
    max_budget = request.args.get('max_budget', type=float)
    remote_filter = request.args.get('remote_friendly', '')
    
    query = Gig.query.filter_by(status='open', removed_by_admin=False)
    
    # Filter executions
    if search_query:
        query = query.filter((Gig.title.ilike(f'%{search_query}%')) | (Gig.description.ilike(f'%{search_query}%')))
    if university_filter:
        query = query.filter_by(university=university_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)
    if min_budget is not None:
        query = query.filter(Gig.budget >= min_budget)
    if max_budget is not None:
        query = query.filter(Gig.budget <= max_budget)
    if remote_filter == 'yes':
        query = query.filter(Gig.location_type == 'Remote — any university')
    elif remote_filter == 'no':
        query = query.filter(Gig.location_type == 'On-campus — specific university')
        
    query = query.order_by(Gig.created_at.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    gigs = pagination.items
    
    return render_template('freelance/browse.html',
                           gigs=gigs,
                           pagination=pagination,
                           search=search_query,
                           university_f=university_filter,
                           category_f=category_filter,
                           min_budget=min_budget,
                           max_budget=max_budget,
                           remote_f=remote_filter)


@freelance_bp.route('/freelance/create', methods=['GET', 'POST'])
@login_required
def create_gig():
    errors = {}
    form_data = {}
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category = request.form.get('category', '')
        deadline = request.form.get('deadline', '').strip()
        location_type = request.form.get('location_type', '').strip()
        budget_type = request.form.get('budget_type', 'fixed').strip()
        
        # Determine university setting depending on location type choice
        if location_type == 'On-campus — specific university':
            university = request.form.get('university', '').strip()
        else:
            university = 'Remote (All Campus Node Access)'
            
        form_data = {
            'title': title,
            'description': description,
            'category': category,
            'deadline': deadline,
            'location_type': location_type,
            'budget_type': budget_type,
            'university': university
        }
        
        # Validation checks
        if not title:
            errors['title'] = 'Job title is required'
        if not description:
            errors['description'] = 'Details are required'
        if not deadline:
            errors['deadline'] = 'Deadline is required'
        if category not in GIG_CATEGORIES:
            errors['category'] = 'Please select a job category'
            
        # Budget evaluation based on fixed price vs budget ranges
        budget_val = 0.0
        budget_min_val = None
        
        if budget_type == 'range':
            budget_min_str = request.form.get('budget_min', '').strip()
            budget_max_str = request.form.get('budget_max', '').strip()
            form_data['budget_min'] = budget_min_str
            form_data['budget'] = budget_max_str # Max budget stored in main budget column
            
            if not budget_min_str or not budget_max_str:
                errors['budget'] = 'Please supply both min and max budgets'
            else:
                try:
                    budget_min_val = float(budget_min_str)
                    budget_val = float(budget_max_str)
                    if budget_min_val <= 0 or budget_val <= 0:
                        errors['budget'] = 'Budgets must be greater than 0'
                    elif budget_val < budget_min_val:
                        errors['budget'] = 'Max budget cannot be less than min budget'
                except ValueError:
                    errors['budget'] = 'Enter valid budget numbers'
        else:
            budget_str = request.form.get('budget', '').strip()
            form_data['budget'] = budget_str
            if not budget_str:
                errors['budget'] = 'Budget is required'
            else:
                try:
                    budget_val = float(budget_str)
                    if budget_val <= 0:
                        errors['budget'] = 'Budget must be greater than 0'
                except ValueError:
                    errors['budget'] = 'Enter valid budget amount'
                    
        # On-campus specific location check
        if location_type == 'On-campus — specific university':
            if not university or university not in UNIVERSITIES:
                errors['university'] = 'Valid university campus must be chosen'
                
        if not errors:
            new_gig = Gig(
                client_id=current_user.id,
                title=title,
                description=description,
                budget=budget_val,
                budget_min=budget_min_val,
                budget_type=budget_type,
                deadline=deadline,
                category=category,
                university=university,
                location_type=location_type,
                remote_friendly=(location_type == 'Remote — any university'),
                status='open'
            )
            
            db.session.add(new_gig)
            db.session.commit()
            
            flash('Success! Gig published on board.', 'success')
            return redirect(url_for('freelance.browse'))
            
    return render_template('freelance/create.html', errors=errors, form_data=form_data)


@freelance_bp.route('/freelance/<int:gig_id>', methods=['GET', 'POST'])
def detail(gig_id):
    gig = Gig.query.get_or_404(gig_id)
    proposals = Proposal.query.filter_by(gig_id=gig.id).order_by(Proposal.created_at.desc()).all()
    
    # Check if current logged-in user already sent a proposal
    existing_proposal = None
    if current_user.is_authenticated:
        existing_proposal = Proposal.query.filter_by(gig_id=gig.id, freelancer_id=current_user.id).first()
        
    errors = {}
    form_data = {}
    
    if existing_proposal:
        form_data = {
            'price': str(existing_proposal.price),
            'delivery_time': existing_proposal.delivery_time,
            'message': existing_proposal.message
        }
    
    # Proposal submission or modification
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=url_for('freelance.detail', gig_id=gig.id)))
            
        if gig.client_id == current_user.id:
            flash('Error: You cannot submit proposals for your own Gig.', 'danger')
            return redirect(url_for('freelance.detail', gig_id=gig.id))

        if current_user.account_type not in ('seller', 'admin'):
            flash('Only seller accounts can submit proposals. Upgrade in Profile Settings.', 'warning')
            return redirect(url_for('freelance.detail', gig_id=gig.id))
            
        if gig.status != 'open':
            flash('Error: This gig is no longer accepting bids.', 'danger')
            return redirect(url_for('freelance.detail', gig_id=gig.id))
            
        price_str = request.form.get('price', '').strip()
        delivery_time = request.form.get('delivery_time', '').strip()
        message = request.form.get('message', '').strip()
        
        form_data = {
            'price': price_str,
            'delivery_time': delivery_time,
            'message': message
        }
        
        price = 0.0
        if not price_str:
            errors['price'] = 'Bid price is required'
        else:
            try:
                price = float(price_str)
                if price <= 0:
                    errors['price'] = 'Bid price must be greater than 0'
            except ValueError:
                errors['price'] = 'Enter valid bid price'
                
        if not message:
            errors['message'] = 'Proposal message details required'
        if not delivery_time:
            errors['delivery_time'] = 'Delivery timeframe is required'
            
        if not errors:
            if existing_proposal:
                # Update existing proposal instead of submitting multiple
                existing_proposal.price = price
                existing_proposal.delivery_time = delivery_time
                existing_proposal.message = message
                existing_proposal.created_at = datetime.utcnow()
                db.session.commit()
                flash('Success! Your proposal has been updated.', 'success')
            else:
                # Create brand new proposal
                new_proposal = Proposal(
                    gig_id=gig.id,
                    freelancer_id=current_user.id,
                    price=price,
                    delivery_time=delivery_time,
                    message=message,
                    status='pending'
                )
                db.session.add(new_proposal)
                
                # Notify gig owner about the new proposal
                n = Notification(
                    user_id=gig.client_id,
                    notification_type='proposal',
                    message=f"New proposal of GHS {price:,.2f} from {current_user.full_name} for '{gig.title}'",
                    link=url_for('freelance.detail', gig_id=gig.id)
                )
                db.session.add(n)
                db.session.commit()
                flash('Success! Your proposal has been submitted.', 'success')
                
            return redirect(url_for('freelance.detail', gig_id=gig.id))
            
    return render_template('freelance/detail.html', 
                           gig=gig, 
                           proposals=proposals, 
                           has_proposed=(existing_proposal is not None), 
                           errors=errors, 
                           form_data=form_data)


@freelance_bp.route('/freelance/proposal/<int:proposal_id>/accept', methods=['POST'])
@login_required
def accept_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)
    gig = proposal.gig
    
    # State validation & Ownership check
    if gig.client_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('freelance.detail', gig_id=gig.id))
        
    if gig.status != 'open':
        flash('Error: This gig has already been assigned or closed.', 'danger')
        return redirect(url_for('freelance.detail', gig_id=gig.id))
        
    # Redirect to secure Paystack escrow checkout page to pay upfront entry commitment
    return redirect(url_for('payments.checkout', gig_id=gig.id, proposal_id=proposal.id))


@freelance_bp.route('/freelance/<int:gig_id>/complete', methods=['POST'])
@login_required
def mark_complete(gig_id):
    gig = Gig.query.get_or_404(gig_id)
    
    if gig.client_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('freelance.detail', gig_id=gig.id))
        
    if gig.status != 'in_progress':
        flash('Error: This gig is not currently in progress.', 'danger')
        return redirect(url_for('freelance.detail', gig_id=gig.id))
        
    gig.status = 'completed'
    
    # Find accepted proposal to notify freelancer
    accepted_p = Proposal.query.filter_by(gig_id=gig.id, status='accepted').first()
    if accepted_p:
        n = Notification(
            user_id=accepted_p.freelancer_id,
            notification_type='completed',
            message=f"Great news! Your work on '{gig.title}' has been marked complete. Escrow funds will release.",
            link=url_for('freelance.detail', gig_id=gig.id)
        )
        db.session.add(n)
        
    db.session.commit()
    flash('Success! You have marked this task as Completed.', 'success')
    return redirect(url_for('freelance.detail', gig_id=gig.id))


@freelance_bp.route('/freelance/<int:gig_id>/cancel', methods=['POST'])
@login_required
def cancel_gig(gig_id):
    gig = Gig.query.get_or_404(gig_id)
    
    if gig.client_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('freelance.detail', gig_id=gig.id))
        
    if gig.status != 'open':
        flash('Error: Can only cancel open gigs.', 'danger')
        return redirect(url_for('freelance.detail', gig_id=gig.id))
        
    gig.status = 'cancelled'
    
    # Notify pending proposers
    proposals = Proposal.query.filter_by(gig_id=gig.id, status='pending').all()
    for p in proposals:
        p.status = 'cancelled'
        n = Notification(
            user_id=p.freelancer_id,
            notification_type='rejected',
            message=f"The job gig '{gig.title}' has been cancelled by the client.",
            link=url_for('freelance.browse')
        )
        db.session.add(n)
        
    db.session.commit()
    flash('Success! This gig has been cancelled.', 'warning')
    return redirect(url_for('freelance.browse'))


@freelance_bp.route('/my-gigs')
@login_required
def my_gigs():
    posted_gigs_created = Gig.query.filter_by(client_id=current_user.id).order_by(Gig.created_at.desc()).all()
    bids_submitted = Proposal.query.filter_by(freelancer_id=current_user.id).order_by(Proposal.created_at.desc()).all()
    
    return render_template('freelance/my_gigs.html', posted_gigs=posted_gigs_created, proposals=bids_submitted)


@freelance_bp.route('/freelance/showcases')
def showcases_list():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    query = ShowcasePost.query.order_by(ShowcasePost.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    showcases = pagination.items
    
    # Check what posts current user liked
    liked_post_ids = set()
    if current_user.is_authenticated:
        likes = ShowcaseLike.query.filter_by(user_id=current_user.id).all()
        liked_post_ids = {l.post_id for l in likes}
        
    return render_template('freelance/showcases.html',
                           showcases=showcases,
                           pagination=pagination,
                           liked_post_ids=liked_post_ids)


@freelance_bp.route('/freelance/showcases/<int:post_id>')
def showcase_detail(post_id):
    post = ShowcasePost.query.get_or_404(post_id)
    liked = False
    if current_user.is_authenticated:
        liked = ShowcaseLike.query.filter_by(user_id=current_user.id, post_id=post.id).first() is not None
    return render_template('freelance/showcase_detail.html', post=post, liked=liked)


@freelance_bp.route('/freelance/showcases/create', methods=['GET', 'POST'])
@login_required
def create_showcase():
    if current_user.account_type not in ('seller', 'admin'):
        flash('Only seller accounts can create showcase posts. Upgrade in Profile Settings.', 'warning')
        return redirect(url_for('freelance.showcases_list'))

    errors = {}
    form_data = {}
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        
        form_data = {
            'title': title,
            'content': content
        }
        
        if not title:
            errors['title'] = 'Title is required'
        if not content:
            errors['content'] = 'Description of your showcase is required'
            
        media_urls = []
        uploaded_files = request.files.getlist('media')
        uploaded_files = [f for f in uploaded_files if f.filename != '']
        
        if not uploaded_files:
            errors['media'] = 'At least one image is required'
        elif len(uploaded_files) > 3:
            errors['media'] = 'You can upload a maximum of 3 images'
            
        for file in uploaded_files:
            if 'media' not in errors:
                from werkzeug.utils import secure_filename
                import time
                import os
                from flask import current_app
                
                ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
                filename = secure_filename(file.filename)
                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                
                if ext not in ALLOWED_EXTENSIONS:
                    errors['media'] = 'Allowed file formats: PNG, JPG, JPEG, WEBP, GIF'
                    break
                
                file.seek(0, 2)
                size_bytes = file.tell()
                file.seek(0)
                if size_bytes > 5 * 1024 * 1024:
                    errors['media'] = 'Each image must be less than 5 MB'
                    break
                    
                try:
                    img = Image.open(file)
                    img.verify()
                    file.seek(0)
                except Exception:
                    errors['media'] = 'File appears to be corrupted or is not a valid image'
                    break
                    
                filename = f"showcase_{int(time.time())}_{len(media_urls)}_{filename}"
                upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
                os.makedirs(upload_folder, exist_ok=True)
                file_path = os.path.join(upload_folder, filename)
                file.save(file_path)
                media_urls.append(f"/static/uploads/{filename}")
                
        if not errors:
            new_post = ShowcasePost(
                user_id=current_user.id,
                title=title,
                content=content,
                media_url=media_urls[0] if media_urls else None,
                media_urls=','.join(media_urls) if media_urls else None
            )
            db.session.add(new_post)
            db.session.commit()
            
            flash('Success! Your showcase post is published to the feed.', 'success')
            return redirect(url_for('freelance.showcases_list'))
            
    return render_template('freelance/create_showcase.html', errors=errors, form_data=form_data)


@freelance_bp.route('/freelance/showcases/<int:post_id>/like', methods=['POST'])
@login_required
def like_showcase(post_id):
    post = ShowcasePost.query.get_or_404(post_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    existing_like = ShowcaseLike.query.filter_by(post_id=post.id, user_id=current_user.id).first()
    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        liked = False
    else:
        new_like = ShowcaseLike(post_id=post.id, user_id=current_user.id)
        db.session.add(new_like)
        db.session.commit()
        liked = True
    
    count = ShowcaseLike.query.filter_by(post_id=post.id).count()
    
    if is_ajax:
        return jsonify({'success': True, 'liked': liked, 'count': count})
    return redirect(request.referrer or url_for('freelance.showcases_list'))


@freelance_bp.route('/freelance/showcases/<int:post_id>/comment', methods=['POST'])
@login_required
def comment_showcase(post_id):
    post = ShowcasePost.query.get_or_404(post_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    content = request.form.get('content', '').strip()
    if not content:
        if is_ajax:
            return jsonify({'success': False, 'error': 'Comment cannot be empty.'}), 400
        flash('Comment cannot be empty.', 'danger')
        return redirect(request.referrer or url_for('freelance.showcases_list'))
        
    comment = ShowcaseComment(post_id=post.id, user_id=current_user.id, content=content)
    db.session.add(comment)
    db.session.commit()
    
    count = ShowcaseComment.query.filter_by(post_id=post.id).count()
    
    if is_ajax:
        avatar = current_user.avatar or 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&w=150&q=80'
        return jsonify({
            'success': True,
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'user_id': current_user.id,
                'user_name': current_user.full_name,
                'user_avatar': avatar,
                'created_at': comment.created_at.strftime('%d %b %Y at %H:%M'),
            },
            'count': count
        })
    flash('Comment added successfully!', 'success')
    return redirect(request.referrer or url_for('freelance.showcases_list'))


@freelance_bp.route('/freelance/showcases/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_showcase(post_id):
    post = ShowcasePost.query.get_or_404(post_id)
    
    if post.user_id != current_user.id and not current_user.is_admin:
        abort(403)
        
    db.session.delete(post)
    db.session.commit()
    flash('Showcase post removed.', 'success')
    return redirect(url_for('freelance.showcases_list'))

