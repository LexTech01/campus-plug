from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, abort
from flask_login import login_required, current_user
from sqlalchemy import update as sa_update
from models import db, User, Listing, Gig, Transaction, TransactionStatus, TransactionLog, Review, Notification, AdminLog
from datetime import datetime
from blueprints.payments import create_paystack_transfer_recipient, initiate_paystack_transfer, initiate_paystack_refund, prompt_reviews_for_transaction

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def prevent_admin_target(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' in kwargs:
            target = User.query.get(kwargs['user_id'])
            if target and target.is_admin:
                flash('Cannot perform actions on another admin account.', 'danger')
                return redirect(url_for('admin.users_list'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/admin/dashboard')
@login_required
@admin_required
def dashboard():
    # Sum up metrics server-side
    total_users = User.query.count()
    total_listings = Listing.query.count()
    total_gigs = Gig.query.count()
    
    # Platform volume & earnings
    released_txns = Transaction.query.filter_by(status=TransactionStatus.released).all()
    total_volume = sum(t.amount for t in released_txns)
    total_revenue = sum(t.platform_fee for t in released_txns)
    
    held_escrow_count = Transaction.query.filter_by(status=TransactionStatus.held_in_escrow).count()
    disputed_count = Transaction.query.filter_by(status=TransactionStatus.disputed).count()
    
    metrics = {
        'total_users': total_users,
        'total_listings': total_listings,
        'total_gigs': total_gigs,
        'total_volume': total_volume,
        'total_revenue': total_revenue,
        'held_escrow_count': held_escrow_count,
        'disputed_count': disputed_count
    }
    
    # Get recent admin action logs
    recent_logs = AdminLog.query.order_by(AdminLog.created_at.desc()).limit(5).all()
    
    # Campus Node distribution (for UI) — 3 GROUP BY queries instead of 3N
    from sqlalchemy import func
    user_counts = dict(db.session.query(User.university, func.count(User.id)).group_by(User.university).all())
    listing_counts = dict(db.session.query(Listing.university, func.count(Listing.id)).filter(Listing.removed_by_admin == False).group_by(Listing.university).all())
    gig_counts = dict(db.session.query(Gig.university, func.count(Gig.id)).filter(Gig.removed_by_admin == False).group_by(Gig.university).all())
    
    from models import UNIVERSITIES
    node_metrics = []
    for uni in UNIVERSITIES:
        node_metrics.append({
            'name': uni,
            'user_count': user_counts.get(uni, 0),
            'listing_count': listing_counts.get(uni, 0),
            'gig_count': gig_counts.get(uni, 0)
        })
        
    from datetime import datetime
    return render_template(
        'admin/dashboard.html',
        metrics=metrics,
        recent_logs=recent_logs,
        UNIVERSITIES=UNIVERSITIES,
        node_metrics=node_metrics,
        now=datetime.now
    )

@admin_bp.route('/admin/users')
@login_required
@admin_required
def users_list():
    search = request.args.get('search', '').strip()
    account_filter = request.args.get('account_type', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = User.query
    if search:
        query = query.filter((User.full_name.ilike(f'%{search}%')) | (User.email.ilike(f'%{search}%')) | (User.university.ilike(f'%{search}%')))
    if account_filter:
        query = query.filter(User.account_type == account_filter)
        
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items
    
    return render_template('admin/users.html', users=users, pagination=pagination, search=search, account_filter=account_filter)

@admin_bp.route('/admin/users/<int:user_id>')
@login_required
@admin_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    
    # Admin stats for this specific user
    user_listings = Listing.query.filter_by(seller_id=user.id).all()
    user_gigs = Gig.query.filter_by(client_id=user.id).all()
    
    # Transactions buyer/seller roles
    user_purchases = Transaction.query.filter_by(buyer_id=user.id).all()
    user_sales = Transaction.query.filter_by(seller_id=user.id).all()
    
    # Reviews given + received
    reviews_received = Review.query.filter_by(reviewee_id=user.id).all()
    
    return render_template(
        'admin/user_detail.html',
        user=user,
        listings=user_listings,
        gigs=user_gigs,
        purchases=user_purchases,
        sales=user_sales,
        reviews_received=reviews_received
    )

@admin_bp.route('/admin/users/<int:user_id>/suspend', methods=['POST'])
@login_required
@admin_required
@prevent_admin_target
def suspend_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot suspend your own admin user node!", "danger")
        return redirect(url_for('admin.users_list'))
        
    note = request.form.get('note', '').strip()
    if not note:
        flash("A justification note is required to suspend or lift suspension.", "warning")
        return redirect(url_for('admin.user_detail', user_id=user.id))
        
    user.is_suspended = not user.is_suspended
    
    action_type = 'suspend_user' if user.is_suspended else 'reinstate_user'
    log_msg = f"{current_user.full_name} suspended {user.full_name} ({user.email})." if user.is_suspended else f"{current_user.full_name} reinstated {user.full_name} ({user.email})."
    
    admin_log = AdminLog(
        admin_id=current_user.id,
        action=action_type,
        target_id=user.id,
        note=f"{log_msg} Justification: {note}",
        created_at=datetime.utcnow()
    )
    db.session.add(admin_log)
    db.session.commit()
    
    status_msg = "suspended" if user.is_suspended else "reinstated"
    flash(f"User {user.full_name} has been {status_msg}.", "success")
    return redirect(url_for('admin.user_detail', user_id=user.id))

@admin_bp.route('/admin/listings')
@login_required
@admin_required
def listings_list():
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = Listing.query
    if search:
        query = query.filter((Listing.title.ilike(f'%{search}%')) | (Listing.description.ilike(f'%{search}%')))
        
    pagination = query.order_by(Listing.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    listings = pagination.items
    
    return render_template('admin/listings.html', listings=listings, pagination=pagination, search=search)

@admin_bp.route('/admin/listings/<int:listing_id>/toggle-remove', methods=['POST'])
@login_required
@admin_required
def toggle_remove_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.seller and listing.seller.is_admin:
        flash('Cannot moderate listings belonging to another admin.', 'danger')
        return redirect(url_for('admin.listings_list'))
    note = request.form.get('note', '').strip()
    if not note:
        flash("A moderation note explaining the action is required.", "warning")
        return redirect(request.referrer or url_for('admin.listings_list'))
        
    listing.removed_by_admin = not listing.removed_by_admin
    
    action_type = 'remove_listing' if listing.removed_by_admin else 'restore_listing'
    log_msg = f"{current_user.full_name} marked listing '{listing.title}' as REMOVED." if listing.removed_by_admin else f"{current_user.full_name} restored listing '{listing.title}'."
    
    admin_log = AdminLog(
        admin_id=current_user.id,
        action=action_type,
        target_id=listing.id,
        note=f"{log_msg} Note: {note}",
        created_at=datetime.utcnow()
    )
    db.session.add(admin_log)
    db.session.commit()
    
    status_msg = "hidden/removed from marketplace" if listing.removed_by_admin else "restored to marketplace"
    flash(f"Listing has been {status_msg}.", "success")
    return redirect(request.referrer or url_for('admin.listings_list'))

@admin_bp.route('/admin/gigs')
@login_required
@admin_required
def gigs_list():
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = Gig.query
    if search:
        query = query.filter((Gig.title.ilike(f'%{search}%')) | (Gig.description.ilike(f'%{search}%')))
        
    pagination = query.order_by(Gig.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    gigs = pagination.items
    
    return render_template('admin/gigs.html', gigs=gigs, pagination=pagination, search=search)

@admin_bp.route('/admin/gigs/<int:gig_id>/toggle-remove', methods=['POST'])
@login_required
@admin_required
def toggle_remove_gig(gig_id):
    gig = Gig.query.get_or_404(gig_id)
    if gig.client and gig.client.is_admin:
        flash('Cannot moderate gigs belonging to another admin.', 'danger')
        return redirect(url_for('admin.gigs_list'))
    note = request.form.get('note', '').strip()
    if not note:
        flash("A moderation note explaining the action is required.", "warning")
        return redirect(request.referrer or url_for('admin.gigs_list'))
        
    gig.removed_by_admin = not gig.removed_by_admin
    
    action_type = 'remove_gig' if gig.removed_by_admin else 'restore_gig'
    log_msg = f"{current_user.full_name} marked gig '{gig.title}' as REMOVED." if gig.removed_by_admin else f"{current_user.full_name} restored gig '{gig.title}'."
    
    admin_log = AdminLog(
        admin_id=current_user.id,
        action=action_type,
        target_id=gig.id,
        note=f"{log_msg} Note: {note}",
        created_at=datetime.utcnow()
    )
    db.session.add(admin_log)
    db.session.commit()
    
    status_msg = "hidden/removed from gigs board" if gig.removed_by_admin else "restored to gigs board"
    flash(f"Gig has been {status_msg}.", "success")
    return redirect(request.referrer or url_for('admin.gigs_list'))

@admin_bp.route('/admin/disputes')
@login_required
@admin_required
def disputes_list():
    disputes = Transaction.query.filter_by(status=TransactionStatus.disputed).order_by(Transaction.created_at.desc()).all()
    # Also fetch completed or resolved ones for log context
    all_admin_logs = AdminLog.query.filter(AdminLog.action.in_(['resolve_dispute_release', 'resolve_dispute_refund'])).order_by(AdminLog.created_at.desc()).all()
    
    return render_template('admin/disputes.html', disputes=disputes, logs=all_admin_logs)

@admin_bp.route('/admin/disputes/<int:transaction_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_dispute(transaction_id):
    txn = Transaction.query.get_or_404(transaction_id)
    decision = request.form.get('decision') # 'release' or 'refund'
    note = request.form.get('note', '').strip()
    
    if not decision or decision not in ['release', 'refund']:
        flash("Invalid dispute resolution selection.", "danger")
        return redirect(url_for('admin.disputes_list'))
        
    if not note:
        flash("An audit log note explaining the decision is strictly required to resolve a dispute.", "warning")
        return redirect(url_for('admin.disputes_list'))
        
    if txn.status != TransactionStatus.disputed:
        flash("This transaction is not currently flagged as disputed.", "danger")
        return redirect(url_for('admin.disputes_list'))
        
    try:
        if decision == 'release':
            # Atomic: only release if still disputed — prevents double-resolution
            result = db.session.execute(
                sa_update(Transaction)
                .where(Transaction.id == transaction_id)
                .where(Transaction.status == TransactionStatus.disputed)
                .values(status=TransactionStatus.released, released_at=datetime.utcnow())
            )
            if result.rowcount == 0:
                flash("This dispute has already been resolved.", "danger")
                return redirect(url_for('admin.disputes_list'))
            
            # Log the state transition
            db.session.add(TransactionLog(
                transaction_id=txn.id,
                old_status=TransactionStatus.disputed.value,
                new_status=TransactionStatus.released.value,
                changed_at=datetime.utcnow()
            ))
            
            vendor = User.query.get(txn.seller_id)
            if not vendor or not vendor.phone or not vendor.momo_provider:
                flash(f"Vendor client {txn.seller.full_name} has no Mobile Money recipient configured. Dispute cannot be released.", "danger")
                return redirect(url_for('admin.disputes_list'))
                
            recipient_code = create_paystack_transfer_recipient(
                name=vendor.full_name,
                account_number=vendor.phone,
                momo_provider=vendor.momo_provider
            )
            
            prompt_reviews_for_transaction(txn, db.session)
            
            payout_sent = False
            if recipient_code:
                transfer_code = initiate_paystack_transfer(
                    amount_ghs=txn.seller_payout_amount,
                    recipient_code=recipient_code,
                    reason=f"Campus Plug Dispute Release ID {txn.id}"
                )
                if transfer_code:
                    txn.paystack_transfer_code = transfer_code
                    payout_sent = True
                    
            # Record audit actions
            admin_log = AdminLog(
                admin_id=current_user.id,
                action='resolve_dispute_release',
                target_id=txn.id,
                note=f"Dispute Resolved: Escrow Released to Seller. Note: {note}",
                created_at=datetime.utcnow()
            )
            db.session.add(admin_log)
            
            # Send notifications
            n_seller = Notification(
                user_id=txn.seller_id,
                notification_type='bell',
                message=f"Dispute Resolved! Escrow funds of GHS {txn.seller_payout_amount:.2f} have been released to your MoMo account. Note: {note}",
                link='/payments/dashboard'
            )
            n_buyer = Notification(
                user_id=txn.buyer_id,
                notification_type='bell',
                message=f"Dispute Resolved: Escrow funds of GHS {txn.amount:.2f} have been released to Seller. Note: {note}",
                link='/payments/dashboard'
            )
            db.session.add_all([n_seller, n_buyer])
            db.session.commit()
            
            if payout_sent:
                flash(f"Dispute resolved successfully! GHS {txn.seller_payout_amount:.2f} has been transferred directly to {vendor.full_name}'s MoMo account.", "success")
            else:
                flash(f"Dispute resolved in system! MoMo transfer was logged for manual payout administrative dispatch.", "warning")
                
        else: # refund
            # Atomic: only refund if still disputed
            result = db.session.execute(
                sa_update(Transaction)
                .where(Transaction.id == transaction_id)
                .where(Transaction.status == TransactionStatus.disputed)
                .values(status=TransactionStatus.refunded)
            )
            if result.rowcount == 0:
                flash("This dispute has already been resolved.", "danger")
                return redirect(url_for('admin.disputes_list'))
            
            db.session.add(TransactionLog(
                transaction_id=txn.id,
                old_status=TransactionStatus.disputed.value,
                new_status=TransactionStatus.refunded.value,
                changed_at=datetime.utcnow()
            ))
            
            if txn.paystack_reference:
                initiate_paystack_refund(txn.paystack_reference)
            
            if txn.listing:
                txn.listing.status = 'active'
            elif txn.gig:
                txn.gig.status = 'open'
                if txn.proposal:
                    txn.proposal.status = 'pending'
                    
            # Record audit actions
            admin_log = AdminLog(
                admin_id=current_user.id,
                action='resolve_dispute_refund',
                target_id=txn.id,
                note=f"Dispute Resolved: Escrow Refunded to Buyer. Note: {note}",
                created_at=datetime.utcnow()
            )
            db.session.add(admin_log)
            
            # Send notifications
            n_seller = Notification(
                user_id=txn.seller_id,
                notification_type='bell',
                message=f"Dispute Resolved: Escrow funds of GHS {txn.amount:.2f} have been refunded to Buyer. Note: {note}",
                link='/payments/dashboard'
            )
            n_buyer = Notification(
                user_id=txn.buyer_id,
                notification_type='bell',
                message=f"Dispute Resolved! GHS {txn.amount:.2f} has been refunded to your account via Mobile Money gateway. Note: {note}",
                link='/payments/dashboard'
            )
            db.session.add_all([n_seller, n_buyer])
            db.session.commit()
            
            flash(f"Dispute resolved! GHS {txn.amount:.2f} has been successfully refunded to the buyer's MoMo account.", "success")
            
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while executing dispute resolution: {e}", "danger")
        
    return redirect(url_for('admin.disputes_list'))

@admin_bp.route('/admin/transactions')
@login_required
@admin_required
def transactions_list():
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    query = Transaction.query
    if search:
        # Search by paystack reference or buyer/seller name
        query = query.join(User, Transaction.buyer_id == User.id).filter(
            (Transaction.paystack_reference.ilike(f'%{search}%')) | 
            (User.full_name.ilike(f'%{search}%')) | 
            (User.email.ilike(f'%{search}%'))
        )
        
    pagination = query.order_by(Transaction.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    transactions = pagination.items
    
    return render_template('admin/transactions.html', transactions=transactions, pagination=pagination, search=search)
