import os
from io import BytesIO
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from models import db, User, Listing, Offer, CATEGORIES, CONDITIONS, DELIVERY_POLICIES, UNIVERSITIES, Notification
from werkzeug.utils import secure_filename
from PIL import Image

marketplace_bp = Blueprint('marketplace', __name__)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def validate_image_content(file_stream):
    try:
        img = Image.open(file_stream)
        img.verify()
        file_stream.seek(0)
        return True
    except Exception:
        return False

def validate_image_size(file_storage, max_mb=5):
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    return size <= max_mb * 1024 * 1024

@marketplace_bp.route('/marketplace')
def browse():
    page = request.args.get('page', 1, type=int)
    per_page = 12 # Show 12 items per page for an attractive responsive grid
    
    # Extract query filters
    search_query = request.args.get('search', '').strip()
    university_filter = request.args.get('university', '').strip()
    category_filter = request.args.get('category', '').strip()
    condition_filter = request.args.get('condition', '').strip()
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    sort_by = request.args.get('sort_by', 'newest')
    
    # Standard base query
    query = Listing.query.filter_by(status='active', removed_by_admin=False)
    
    # App-level filters applied server-side in DB query
    if search_query:
        query = query.filter((Listing.title.ilike(f'%{search_query}%')) | (Listing.description.ilike(f'%{search_query}%')))
    if university_filter:
        query = query.filter_by(university=university_filter)
    if category_filter:
        query = query.filter_by(category=category_filter)
    if condition_filter:
        query = query.filter_by(condition=condition_filter)
    if min_price is not None:
        query = query.filter(Listing.price >= min_price)
    if max_price is not None:
        query = query.filter(Listing.price <= max_price)
        
    # Apply ordering
    if sort_by == 'price_low':
        query = query.order_by(Listing.price.asc())
    elif sort_by == 'price_high':
        query = query.order_by(Listing.price.desc())
    else: # newest
        query = query.order_by(Listing.created_at.desc())
        
    # Paginate results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    listings = pagination.items
    
    return render_template('marketplace/browse.html', 
                           listings=listings, 
                           pagination=pagination,
                           search=search_query,
                           university_f=university_filter,
                           category_f=category_filter,
                           condition_f=condition_filter,
                           min_price=min_price,
                           max_price=max_price,
                           sort_by=sort_by)


@marketplace_bp.route('/marketplace/create', methods=['GET', 'POST'])
@login_required
def create_listing():
    if current_user.account_type not in ('seller', 'admin'):
        flash('Only seller accounts can create marketplace listings. Upgrade in Settings to start selling.', 'warning')
        return redirect(url_for('marketplace.browse'))

    errors = {}
    form_data = {}
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('price', '').strip()
        original_price_str = request.form.get('original_price', '').strip()
        category = request.form.get('category', '')
        condition = request.form.get('condition', '')
        university = request.form.get('university', current_user.university)
        delivery_policy = request.form.get('delivery_policy', '')
        is_negotiable = request.form.get('is_negotiable') == 'on'
        quantity_str = request.form.get('quantity', '1')
        
        # Save state to replenish form on error
        form_data = {
            'title': title,
            'description': description,
            'price': price_str,
            'original_price': original_price_str,
            'category': category,
            'condition': condition,
            'university': university,
            'delivery_policy': delivery_policy,
            'is_negotiable': is_negotiable,
            'quantity': quantity_str
        }
        
        # Validations
        if not title:
            errors['title'] = 'Title is required'
        elif len(title) > 100:
            errors['title'] = 'Title must be less than 100 characters'
            
        if not description:
            errors['description'] = 'Description is required'
            
        price = 0.0
        if not price_str:
            errors['price'] = 'Price is required'
        else:
            try:
                price = float(price_str)
                if price <= 0:
                    errors['price'] = 'Price must be greater than GHS 0'
            except ValueError:
                errors['price'] = 'Please enter a valid price amount'
                
        if category not in CATEGORIES:
            errors['category'] = 'Please select a valid category'
            
        if condition not in CONDITIONS:
            errors['condition'] = 'Please select item condition'
            
        if delivery_policy not in DELIVERY_POLICIES:
            errors['delivery_policy'] = 'Please select delivery/pickup policy'
            
        quantity = 1
        try:
            quantity = int(quantity_str)
            if quantity < 0:
                errors['quantity'] = 'Quantity cannot be negative'
            elif quantity == 0:
                errors['quantity'] = 'Quantity must be at least 1'
            elif quantity > 999:
                errors['quantity'] = 'Quantity cannot exceed 999'
        except ValueError:
            errors['quantity'] = 'Enter a valid number'
            
        # File/Photo upload handlers (limited to 3)
        photos_urls = []
        uploaded_files = request.files.getlist('photos')
        
        # Filter empty file uploads (browser sends an empty upload entry if no file is chosen)
        uploaded_files = [f for f in uploaded_files if f.filename != '']
        
        if not uploaded_files:
            errors['photos'] = 'At least one photo is required'
        elif len(uploaded_files) > 3:
            errors['photos'] = 'You can upload a maximum of 3 photos'
            
        for f in uploaded_files:
            if not allowed_file(f.filename):
                errors['photos'] = 'Allowed file formats: PNG, JPG, JPEG, WEBP'
                break
            if not validate_image_content(f):
                errors['photos'] = 'File appears to be corrupted or is not a valid image'
                break
            if not validate_image_size(f, 5):
                errors['photos'] = 'Each photo must be less than 5 MB'
                break
                
        # Parse original_price for discount display
        original_price = None
        discount_percent = None
        if original_price_str:
            try:
                orig = float(original_price_str)
                if orig <= 0:
                    errors['original_price'] = 'Original price must be greater than GHS 0'
                elif orig <= price:
                    errors['original_price'] = 'Original price must be higher than the selling price'
                else:
                    original_price = orig
                    discount_percent = int((orig - price) / orig * 100)
            except ValueError:
                errors['original_price'] = 'Please enter a valid original price'

        if not errors:
            # Save uploaded photos to static/uploads
            for idx, file in enumerate(uploaded_files):
                filename = secure_filename(file.filename)
                # Prefix with timestamp to make unique
                import time
                filename = f"{int(time.time())}_{idx}_{filename}"
                file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                photos_urls.append(f"/static/uploads/{filename}")
                
            photos_str = ','.join(photos_urls) if photos_urls else '/static/images/placeholder.jpg'
            
            new_listing = Listing(
                seller_id=current_user.id,
                title=title,
                description=description,
                price=price,
                original_price=original_price,
                discount_percent=discount_percent,
                category=category,
                condition=condition,
                university=university,
                delivery_policy=delivery_policy,
                is_negotiable=is_negotiable,
                quantity=quantity,
                photos=photos_str,
                status='active'
            )
            
            db.session.add(new_listing)
            db.session.commit()
            
            flash('Success! Your listing has been published!', 'success')
            return redirect(url_for('marketplace.browse'))
            
    return render_template('marketplace/create.html', errors=errors, form_data=form_data)


@marketplace_bp.route('/marketplace/<int:listing_id>')
def detail(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Related products query: Same category or university, exclude self
    related_items = Listing.query.filter(
        Listing.status == 'active',
        Listing.id != listing.id,
        (Listing.category == listing.category) | (Listing.university == listing.university)
    ).limit(3).all()
    
    # Offers for this listing (sorted newest first) — only visible to seller
    offers = []
    if current_user.is_authenticated and current_user.id == listing.seller_id:
        offers = Offer.query.filter_by(listing_id=listing.id).order_by(Offer.created_at.desc()).all()
    
    # Buyer's own pending offer
    buyer_offer = None
    if current_user.is_authenticated:
        buyer_offer = Offer.query.filter_by(
            listing_id=listing.id, buyer_id=current_user.id
        ).order_by(Offer.created_at.desc()).first()
    
    return render_template('marketplace/detail.html', listing=listing, related_items=related_items,
                           offers=offers, buyer_offer=buyer_offer)


@marketplace_bp.route('/marketplace/<int:listing_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Security Rule: Only the seller can edit
    if listing.seller_id != current_user.id:
        flash('Unauthorized action. You can only edit your own listings.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))
        
    errors = {}
    form_data = {
        'title': listing.title,
        'description': listing.description,
        'price': listing.price,
        'original_price': listing.original_price or '',
        'category': listing.category,
        'condition': listing.condition,
        'university': listing.university,
        'delivery_policy': listing.delivery_policy
    }
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        price_str = request.form.get('price', '').strip()
        original_price_str = request.form.get('original_price', '').strip()
        category = request.form.get('category', '')
        condition = request.form.get('condition', '')
        university = request.form.get('university', listing.university)
        delivery_policy = request.form.get('delivery_policy', '')
        is_negotiable = request.form.get('is_negotiable') == 'on'
        quantity_str = request.form.get('quantity', '1')
        
        form_data = {
            'title': title,
            'description': description,
            'price': price_str,
            'original_price': original_price_str,
            'category': category,
            'condition': condition,
            'university': university,
            'delivery_policy': delivery_policy,
            'is_negotiable': is_negotiable,
            'quantity': quantity_str
        }
        
        # Validation checks
        if not title:
            errors['title'] = 'Title is required'
        if not description:
            errors['description'] = 'Description is required'
            
        price = 0.0
        try:
            price = float(price_str)
            if price <= 0:
                errors['price'] = 'Price must be greater than GHS 0'
        except ValueError:
            errors['price'] = 'Please enter a valid price amount'
            
        if category not in CATEGORIES:
            errors['category'] = 'Please select a valid category'
            
        if condition not in CONDITIONS:
            errors['condition'] = 'Please select item condition'
            
        if delivery_policy not in DELIVERY_POLICIES:
            errors['delivery_policy'] = 'Please select delivery/pickup policy'
            
        quantity = listing.quantity
        try:
            quantity = int(quantity_str)
            if quantity < 0:
                errors['quantity'] = 'Quantity cannot be negative'
            elif quantity > 999:
                errors['quantity'] = 'Quantity cannot exceed 999'
        except ValueError:
            errors['quantity'] = 'Enter a valid number'
            
        if university not in UNIVERSITIES:
            errors['university'] = 'Please select a valid university'
            
        # Discount fields validation
        original_price = None
        discount_percent = None
        if original_price_str:
            try:
                orig = float(original_price_str)
                if orig <= 0:
                    errors['original_price'] = 'Original price must be greater than GHS 0'
                elif orig <= price:
                    errors['original_price'] = 'Original price must be higher than the selling price'
                else:
                    original_price = orig
                    discount_percent = int((orig - price) / orig * 100)
            except ValueError:
                errors['original_price'] = 'Please enter a valid original price'

        if not errors:
            # Perform update
            listing.title = title
            listing.description = description
            listing.price = price
            listing.original_price = original_price
            listing.discount_percent = discount_percent
            listing.category = category
            listing.condition = condition
            listing.university = university
            listing.delivery_policy = delivery_policy
            listing.is_negotiable = is_negotiable
            listing.quantity = quantity
            
            # Handle photo changes (removed + new)
            existing_photos = listing.photo_list
            # Remove placeholder from list if present
            existing_photos = [p for p in existing_photos if not p.endswith('placeholder.jpg')]

            # Photos marked for removal
            remove_photos_raw = request.form.get('remove_photos', '').strip()
            remove_urls = [u.strip() for u in remove_photos_raw.split(',') if u.strip()] if remove_photos_raw else []

            # New uploads
            uploaded_files = request.files.getlist('photos')
            uploaded_files = [f for f in uploaded_files if f.filename != '']

            new_urls = []
            for f in uploaded_files:
                if allowed_file(f.filename) and validate_image_content(f):
                    import time
                    filename = secure_filename(f.filename)
                    filename = f"{int(time.time())}_{len(existing_photos) + len(new_urls)}_{filename}"
                    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                    f.save(file_path)
                    new_urls.append(f"/static/uploads/{filename}")

            # Keep photos not in remove list
            kept_photos = [p for p in existing_photos if p not in remove_urls]
            final_photos = kept_photos + new_urls

            if len(final_photos) > 3:
                errors['photos'] = 'You can have a maximum of 3 photos total'

        if not errors:
            listing.photos = ','.join(final_photos) if final_photos else '/static/images/placeholder.jpg'

            # Delete removed files from disk
            for url in remove_urls:
                rel_path = url.replace('/static/', '')
                abs_path = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', rel_path))
                uploads_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'uploads'))
                if abs_path.startswith(uploads_dir) and os.path.isfile(abs_path):
                    os.remove(abs_path)
                    
            db.session.commit()
            flash('Success! Listing updated correctly.', 'success')
            return redirect(url_for('marketplace.detail', listing_id=listing.id))
            
    return render_template('marketplace/edit.html', errors=errors, form_data=form_data, listing=listing)


@marketplace_bp.route('/marketplace/<int:listing_id>/offer', methods=['POST'])
@login_required
def make_offer(listing_id):
    listing = Listing.query.get_or_404(listing_id)

    if current_user.id == listing.seller_id:
        flash('You cannot make an offer on your own listing.', 'warning')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    if not listing.is_negotiable:
        flash('This listing is not accepting offers.', 'warning')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    if listing.status != 'active' or listing.is_sold_out:
        flash('This listing is no longer available.', 'warning')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    price_str = request.form.get('offer_price', '').strip()
    message = request.form.get('offer_message', '').strip()

    if not price_str:
        flash('Please enter an offer price.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    if len(message) > 2000:
        flash('Offer message too long (max 2000 characters).', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    try:
        price = float(price_str)
        if price <= 0:
            flash('Offer price must be greater than GHS 0.', 'danger')
            return redirect(url_for('marketplace.detail', listing_id=listing.id))
    except ValueError:
        flash('Please enter a valid offer price.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    offer = Offer(
        listing_id=listing.id,
        buyer_id=current_user.id,
        price=price,
        message=message or None,
        status='pending'
    )
    db.session.add(offer)

    n = Notification(
        user_id=listing.seller_id,
        notification_type='offer',
        message=f"New offer of GHS {price:,.2f} from {current_user.full_name} for '{listing.title}'",
        link=url_for('marketplace.detail', listing_id=listing.id)
    )
    db.session.add(n)
    db.session.commit()

    flash(f'Your offer of GHS {price:,.2f} has been sent to the seller.', 'success')
    return redirect(url_for('marketplace.detail', listing_id=listing.id))


@marketplace_bp.route('/marketplace/<int:listing_id>/offer/<int:offer_id>/respond', methods=['POST'])
@login_required
def respond_offer(listing_id, offer_id):
    listing = Listing.query.get_or_404(listing_id)
    offer = Offer.query.get_or_404(offer_id)

    if current_user.id != listing.seller_id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    if offer.listing_id != listing.id:
        flash('Offer does not match this listing.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    if offer.status != 'pending':
        flash('This offer has already been responded to.', 'warning')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    action = request.form.get('action', '')
    note = request.form.get('seller_note', '').strip()

    if action == 'accept':
        offer.status = 'accepted'
        flash('Offer accepted! The buyer can now purchase at the agreed price.', 'success')
    elif action == 'counter':
        counter_str = request.form.get('counter_price', '').strip()
        if not counter_str:
            flash('Please enter a counter price.', 'danger')
            return redirect(url_for('marketplace.detail', listing_id=listing.id))
        try:
            counter_price = float(counter_str)
            if counter_price <= 0:
                flash('Counter price must be greater than GHS 0.', 'danger')
                return redirect(url_for('marketplace.detail', listing_id=listing.id))
        except ValueError:
            flash('Please enter a valid counter price.', 'danger')
            return redirect(url_for('marketplace.detail', listing_id=listing.id))
        offer.price = counter_price
        offer.status = 'countered'
        offer.seller_note = note or None
        flash(f'Counter offer of GHS {counter_price:,.2f} sent to buyer.', 'success')
    elif action == 'decline':
        offer.status = 'declined'
        offer.seller_note = note or None
        flash('Offer declined.', 'info')
    else:
        flash('Invalid action.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))

    n = Notification(
        user_id=offer.buyer_id,
        notification_type='offer_response',
        message=f"Your offer of GHS {offer.price:,.2f} for '{listing.title}' was {offer.status} by the seller.",
        link=url_for('marketplace.detail', listing_id=listing.id)
    )
    db.session.add(n)
    db.session.commit()

    return redirect(url_for('marketplace.detail', listing_id=listing.id))


@marketplace_bp.route('/marketplace/<int:listing_id>/mark_sold', methods=['POST'])
@login_required
def mark_sold(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Enforce seller ownership
    if listing.seller_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))
        
    listing.status = 'sold'
    db.session.commit()
    flash('Listing marked as Sold successfully.', 'success')
    return redirect(url_for('marketplace.my_listings'))


@marketplace_bp.route('/marketplace/<int:listing_id>/delete', methods=['POST'])
@login_required
def delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Enforce seller ownership
    if listing.seller_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('marketplace.detail', listing_id=listing.id))
        
    listing.status = 'deleted'
    db.session.commit()
    flash('Listing deleted successfully.', 'info')
    return redirect(url_for('marketplace.my_listings'))


@marketplace_bp.route('/my-listings')
@login_required
def my_listings():
    if current_user.account_type not in ('seller', 'admin'):
        flash('Only seller accounts can view listings. Upgrade in Settings to start selling.', 'warning')
        return redirect(url_for('index'))

    # Fetch all user listings active or sold, exclude deleted
    user_listings = Listing.query.filter(
        Listing.seller_id == current_user.id,
        Listing.status != 'deleted'
    ).order_by(Listing.created_at.desc()).all()
    
    return render_template('marketplace/my_listings.html', listings=user_listings)
