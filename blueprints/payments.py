import hmac
import hashlib
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from sqlalchemy import text, update as sa_update
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, jsonify
from flask_login import login_required, current_user
from extensions import csrf
from models import db, User, Listing, Gig, Transaction, Proposal, Notification, TransactionStatus, Review

payments_bp = Blueprint('payments', __name__)

# CONSTANTS / UTILS
MOMO_PROVIDERS = [
    'MTN Mobile Money',
    'Telecel Cash',
    'AirtelTigo Money'
]

def paystack_headers():
    return {
        "Authorization": f"Bearer {current_app.config['PAYSTACK_SECRET_KEY']}",
        "Content-Type": "application/json",
        "User-Agent": "Campus-Plug-Server"
    }

def initialize_paystack_transaction(email, amount_ghs, reference, callback_url, metadata=None):
    amount_pesewas = int(round(amount_ghs * 100))
    url = "https://api.paystack.co/transaction/initialize"
    payload = {
        "email": email,
        "amount": amount_pesewas,
        "reference": reference,
        "callback_url": callback_url,
        "currency": "GHS",
        "metadata": metadata or {}
    }
    if not current_app.config.get('PAYSTACK_SECRET_KEY') or 'sk_test_' not in current_app.config['PAYSTACK_SECRET_KEY']:
        current_app.logger.error("Paystack secret key is missing or invalid. Set PAYSTACK_SECRET_KEY in .env")
        return None
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=paystack_headers(), method='POST')
        with urllib.request.urlopen(req, timeout=15) as f:
            response_json = json.loads(f.read().decode('utf-8'))
            if response_json.get('status'):
                return response_json['data']['authorization_url']
            current_app.logger.error(f"Paystack returned error: {response_json}")
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        current_app.logger.error(f"Paystack initialization HTTP Error {e.code}: {body}")
    except Exception as e:
        current_app.logger.error(f"Paystack initialization exception: {e}")
    return None

def verify_paystack_transaction(reference):
    safe_reference = urllib.parse.quote(reference)
    url = f"https://api.paystack.co/transaction/verify/{safe_reference}"
    try:
        req = urllib.request.Request(url, headers=paystack_headers(), method='GET')
        with urllib.request.urlopen(req, timeout=15) as f:
            response_json = json.loads(f.read().decode('utf-8'))
            if response_json.get('status'):
                return response_json['data']
    except urllib.error.HTTPError as e:
        current_app.logger.error(f"Paystack verification HTTP Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        current_app.logger.error(f"Paystack transaction verification exception: {e}")
    return None

def create_paystack_transfer_recipient(name, account_number, momo_provider):
    p = momo_provider.lower()
    if 'mtn' in p:
        bank_code = 'MTN'
    elif 'telecel' in p or 'vodafone' in p or 'tf' in p or 'vod' in p:
        bank_code = 'VOD'
    elif 'airtel' in p or 'tigo' in p or 'atl' in p:
        bank_code = 'ATL'
    else:
        bank_code = 'MTN'

    url = "https://api.paystack.co/transferrecipient"
    payload = {
        "type": "mobile_money",
        "name": name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": "GHS"
    }
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=paystack_headers(), method='POST')
        with urllib.request.urlopen(req, timeout=15) as f:
            response_json = json.loads(f.read().decode('utf-8'))
            if response_json.get('status'):
                return response_json['data']['recipient_code']
    except urllib.error.HTTPError as e:
        current_app.logger.error(f"Paystack recipient creation HTTP Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        current_app.logger.error(f"Paystack recipient creation exception: {e}")
    return None

def initiate_paystack_transfer(amount_ghs, recipient_code, reason="Escrow Release"):
    amount_pesewas = int(round(amount_ghs * 100))
    url = "https://api.paystack.co/transfer"
    payload = {
        "source": "balance",
        "amount": amount_pesewas,
        "recipient": recipient_code,
        "reason": reason,
        "currency": "GHS"
    }
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=paystack_headers(), method='POST')
        with urllib.request.urlopen(req, timeout=15) as f:
            response_json = json.loads(f.read().decode('utf-8'))
            if response_json.get('status'):
                return response_json['data']['transfer_code']
    except urllib.error.HTTPError as e:
        current_app.logger.error(f"Paystack dispatch transfer HTTP Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        current_app.logger.error(f"Paystack dispatch transfer exception: {e}")
    return None

def initiate_paystack_refund(reference, amount_ghs=None):
    url = "https://api.paystack.co/refund"
    payload = {
        "transaction": reference
    }
    if amount_ghs:
        payload["amount"] = int(round(amount_ghs * 100))
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=paystack_headers(), method='POST')
        with urllib.request.urlopen(req, timeout=15) as f:
            response_json = json.loads(f.read().decode('utf-8'))
            if response_json.get('status'):
                return response_json['data']
    except urllib.error.HTTPError as e:
        current_app.logger.error(f"Paystack refund operation HTTP Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        current_app.logger.error(f"Paystack refund operation exception: {e}")
    return None


def process_successful_payment(reference, session):
    """
    Common business logic to transition transaction status to held_in_escrow securely,
    and activate listing statuses or proposals.
    """
    txn = Transaction.query.filter_by(paystack_reference=reference).first()
    if not txn:
        return False, "Transaction record not found"
        
    if txn.status == TransactionStatus.held_in_escrow:
        return True, "Payment is already locked in escrow"
        
    if txn.status != TransactionStatus.pending_payment:
        return False, f"Invalid status for escrow lock: {txn.status.name}"
        
    # Standard transaction status lock
    txn.transition_to(TransactionStatus.held_in_escrow, session)
    txn.paid_at = datetime.utcnow()
    
    if txn.context_type == 'listing':
        # Atomic: only decrement if stock available — prevents overselling
        result = session.execute(
            text("UPDATE listings SET quantity = quantity - 1 WHERE id = :id AND quantity > 0"),
            {'id': txn.context_id}
        )
        if result.rowcount == 0:
            return False, "Item is no longer in stock"
        
        listing = Listing.query.get(txn.context_id)
        if listing:
            if listing.quantity == 0:
                listing.status = 'sold'
            
            n_notify = Notification(
                user_id=listing.seller_id,
                notification_type='proposal',
                message=f"GHS {txn.amount:.2f} was locked in secure escrow for '{listing.title}'. Deliver item and confirm receipt to unlock funds.",
                link=url_for('payments.dashboard')
            )
            session.add(n_notify)
            
    elif txn.context_type == 'gig':
        # Atomic: only accept if gig is still open — prevents double-assignment
        result = session.execute(
            text("UPDATE gigs SET status = 'in_progress' WHERE id = :id AND status = 'open'"),
            {'id': txn.context_id}
        )
        if result.rowcount == 0:
            return False, "This gig has already been assigned to another proposal"
        
        proposal = Proposal.query.get(txn.proposal_id)
        if proposal:
            proposal.status = 'accepted'
            
            other_bids = Proposal.query.filter(Proposal.gig_id == txn.context_id, Proposal.id != proposal.id).all()
            for ob in other_bids:
                ob.status = 'declined'
                n_declined = Notification(
                    user_id=ob.freelancer_id,
                    notification_type='rejected',
                    message=f"A challenger candidate was selected for the gig work '{proposal.gig.title}'.",
                    link=url_for('freelance.detail', gig_id=txn.context_id)
                )
                session.add(n_declined)
                
            n_freelancer = Notification(
                user_id=proposal.freelancer_id,
                notification_type='accepted',
                message=f"Congratulations! Your proposal for '{proposal.gig.title}' has been accepted. GHS {txn.amount:.2f} is held in escrow. Deliver work to unlock funds.",
                link=url_for('freelance.detail', gig_id=txn.context_id)
            )
            session.add(n_freelancer)
            
    return True, "Success"


# ROUTES

@payments_bp.route('/payments/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    listing_id = request.args.get('listing_id', type=int)
    gig_id = request.args.get('gig_id', type=int)
    proposal_id = request.args.get('proposal_id', type=int)
    
    listing = Listing.query.get(listing_id) if listing_id else None
    gig = Gig.query.get(gig_id) if gig_id else None
    proposal = Proposal.query.get(proposal_id) if proposal_id else None
    
    if not listing and not (gig and proposal):
        flash("Invalid payment checkout context.", "error")
        return redirect(url_for('index'))
        
    # Safeguard price (calculated solely on backend!)
    amount = listing.price if listing else proposal.price
    seller_id = listing.seller_id if listing else proposal.freelancer_id
    seller = User.query.get(seller_id)
    
    if seller_id == current_user.id:
        flash("You cannot transact with yourself.", "warning")
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        momo_phone = request.form.get('momo_phone', '').strip()
        momo_provider = request.form.get('momo_provider', '').strip()

        errors = {}
        if not re.match(r'^0[0-9]{9}$', momo_phone):
            errors['momo_phone'] = 'Enter a valid Ghana phone number'
        if momo_provider not in [p for p in MOMO_PROVIDERS]:
            errors['momo_provider'] = 'Select a valid MoMo provider'

        if errors:
            return render_template(
                'payments/checkout.html',
                listing=listing,
                gig=gig,
                proposal=proposal,
                amount=amount,
                seller=seller,
                MOMO_PROVIDERS=MOMO_PROVIDERS,
                errors=errors
            )

        current_user.phone = momo_phone
        current_user.momo_provider = momo_provider
        db.session.commit()

        # Determine fees
        platform_fee = round(amount * current_app.config['PLATFORM_FEE_PERCENT'], 2)
        seller_payout_amount = round(amount - platform_fee, 2)
        
        # Apply referral fee waiver if seller has pending waivers
        fee_waiver_used = False
        seller_user = User.query.get(seller_id)
        if seller_user and seller_user.pending_fee_waivers and seller_user.pending_fee_waivers > 0:
            platform_fee = 0.0
            seller_payout_amount = amount
            seller_user.pending_fee_waivers -= 1
            fee_waiver_used = True
        
        # Construct Database transaction representation
        txn = Transaction(
            buyer_id=current_user.id,
            seller_id=seller_id,
            context_type='listing' if listing else 'gig',
            context_id=listing.id if listing else gig.id,
            listing_id=listing.id if listing else None,
            gig_id=gig.id if gig else None,
            proposal_id=proposal.id if proposal else None,
            amount=amount,
            platform_fee=platform_fee,
            seller_payout_amount=seller_payout_amount,
            status=TransactionStatus.pending_payment
        )
        db.session.add(txn)
        if fee_waiver_used:
            flash('Referral fee waiver applied! Your platform fee is GHS 0.00 for this sale.', 'success')
        db.session.flush() # Secure model ID
        
        # Initial logs registration
        txn.transition_to(TransactionStatus.pending_payment, db.session)
        
        # Custom unique reference
        paystack_ref = f"CP_TXN_{txn.id}_{int(time.time())}"
        txn.paystack_reference = paystack_ref
        db.session.commit()
        
        callback_url = url_for('payments.callback', _external=True)
        metadata = {
            "transaction_id": txn.id,
            "context_type": txn.context_type,
            "context_id": txn.context_id,
            "proposal_id": proposal.id if proposal else None
        }
        
        # Create Paystack authorization checkout portal
        auth_url = initialize_paystack_transaction(
            email=current_user.email,
            amount_ghs=amount,
            reference=paystack_ref,
            callback_url=callback_url,
            metadata=metadata
        )
        
        if auth_url:
            return redirect(auth_url)
        else:
            db.session.rollback()
            flash("Payment gateway rejected the request. Check that your Paystack keys in .env are valid test keys from https://dashboard.paystack.com.", "danger")
            return redirect(url_for('payments.checkout', listing_id=listing_id, gig_id=gig_id, proposal_id=proposal_id))
            
    return render_template(
        'payments/checkout.html', 
        listing=listing, 
        gig=gig, 
        proposal=proposal, 
        amount=amount, 
        seller=seller,
        MOMO_PROVIDERS=MOMO_PROVIDERS
    )


@payments_bp.route('/payments/callback')
@login_required
def callback():
    reference = request.args.get('reference')
    if not reference:
        flash("Gateway transaction lookup requires reference details.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    # Verify transaction with paystack first
    data = verify_paystack_transaction(reference)
    if data and data.get('status') == 'success':
        try:
            success, message = process_successful_payment(reference, db.session)
            if success:
                db.session.commit()
                flash("Perfect! Payment secured & locked safely in Escrow. Deliver your item/work now.", "success")
            else:
                if "already locked" in message:
                    flash("Payment is secured in escrow holds.", "success")
                else:
                    flash(f"Escrow hold warning: {message}", "warning")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error finalizing transaction record: {e}")
            flash("An unexpected error occurred while finalizing the transaction. Our team has been notified.", "danger")
    else:
        flash("Transaction was not successfully paid or payment was abandoned at gateway portal.", "danger")
        
    return redirect(url_for('payments.dashboard'))


@payments_bp.route('/payments/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    signature = request.headers.get('x-paystack-signature')
    if not signature:
        return "Missing verification credentials", 400
        
    secret = current_app.config['PAYSTACK_SECRET_KEY'].encode('utf-8')
    computed_signature = hmac.new(secret, request.data, hashlib.sha512).hexdigest()
    
    if not hmac.compare_digest(computed_signature, signature):
        current_app.logger.warning("Paystack Webhook authenticity breach detected!")
        return "Falsified signature credentials", 400
        
    event_payload = request.json
    event_type = event_payload.get('event')
    
    if event_type == 'charge.success':
        data = event_payload.get('data', {})
        reference = data.get('reference')
        if reference:
            try:
                # Independently verify with Paystack API
                verification_data = verify_paystack_transaction(reference)
                if not verification_data or verification_data.get('status') != 'success':
                    current_app.logger.warning(f"Webhook verification failed for reference {reference}")
                    return "Verification failed", 400
                success, message = process_successful_payment(reference, db.session)
                if success:
                    db.session.commit()
                    return "OK", 200
                else:
                    return f"Event processed: {message}", 200
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error in webhook state commitment: {e}")
                return "Internal database error during state update", 500
                
    return "Event skipped", 200


@payments_bp.route('/payments/dashboard')
@login_required
def dashboard():
    purchases = Transaction.query.filter_by(buyer_id=current_user.id).order_by(Transaction.created_at.desc()).all()
    sales = Transaction.query.filter_by(seller_id=current_user.id).order_by(Transaction.created_at.desc()).all()
    
    # Calculate payout holding metrics
    locked_escrow = sum(t.seller_payout_amount for t in sales if t.status == TransactionStatus.held_in_escrow)
    total_released = sum(t.seller_payout_amount for t in sales if t.status == TransactionStatus.released)
    total_disputed = sum(t.seller_payout_amount for t in sales if t.status == TransactionStatus.disputed)
    
    payout_metrics = {
        'locked_escrow': locked_escrow,
        'total_released': total_released,
        'total_disputed': total_disputed
    }
    
    return render_template(
        'payments/dashboard.html', 
        purchases=purchases, 
        sales=sales, 
        payout_metrics=payout_metrics
    )


@payments_bp.route('/payments/release/<int:transaction_id>', methods=['POST'])
@login_required
def release_funds(transaction_id):
    txn = Transaction.query.get_or_404(transaction_id)
    
    if txn.buyer_id != current_user.id:
        flash("Only the purchasing payer/client can release escrow funds.", "danger")
        return redirect(url_for('payments.dashboard'))
    
    # Atomic: only transition if currently held_in_escrow — prevents double-release
    result = db.session.execute(
        sa_update(Transaction)
        .where(Transaction.id == transaction_id)
        .where(Transaction.status == TransactionStatus.held_in_escrow)
        .values(status=TransactionStatus.released, released_at=datetime.utcnow())
    )
    if result.rowcount == 0:
        flash("Funds have already been released or the transaction is in an invalid state.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    vendor = User.query.get(txn.seller_id)
    if not vendor or not vendor.phone or not vendor.momo_provider:
        flash("Payout error: Vendor has not configured a valid Mobile Money number/network on their profile yet.", "warning")
        return redirect(url_for('payments.dashboard'))
        
    try:
        # Create Paystack disbursement target
        recipient_code = create_paystack_transfer_recipient(
            name=vendor.full_name,
            account_number=vendor.phone,
            momo_provider=vendor.momo_provider
        )
        
        # Log the state transition (status + released_at already set atomically above)
        from models import TransactionLog
        log = TransactionLog(
            transaction_id=txn.id,
            old_status=TransactionStatus.held_in_escrow.value,
            new_status=TransactionStatus.released.value,
            changed_at=datetime.utcnow()
        )
        db.session.add(log)
        prompt_reviews_for_transaction(txn, db.session)
        
        # Credit referral rewards
        credit_referral_reward(txn, db.session)
        
        if not recipient_code:
            db.session.commit()
            flash("Funds released in system! Paystack transfer recipient creation failed. Admin flagged reference for manual payout of GHS {:.2f}.".format(txn.seller_payout_amount), "warning")
            return redirect(url_for('payments.dashboard'))
            
        # Dispatch transfer on Paystack
        transfer_code = initiate_paystack_transfer(
            amount_ghs=txn.seller_payout_amount,
            recipient_code=recipient_code,
            reason=f"Campus Plug Released Escrow payout code {txn.id}"
        )
        
        if transfer_code:
            txn.paystack_transfer_code = transfer_code
            db.session.commit()
            flash(f"Boom! GHS {txn.seller_payout_amount:.2f} has been transferred directly to {vendor.full_name}'s MoMo account successfully.", "success")
        else:
            db.session.commit()
            flash("Funds released in escrow! Paystack Transfer API returned an error (OTP or balance limit). System admin flagged reference GHS {:.2f} for manual resolution.".format(txn.seller_payout_amount), "warning")
            
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error executing payout transition: {e}")
        flash("An unexpected error occurred during payout. Our team has been notified.", "danger")
        
    return redirect(url_for('payments.dashboard'))


@payments_bp.route('/payments/dispute/<int:transaction_id>', methods=['POST'])
@login_required
def dispute_funds(transaction_id):
    txn = Transaction.query.get_or_404(transaction_id)
    
    if current_user.id != txn.buyer_id and current_user.id != txn.seller_id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    if txn.status != TransactionStatus.held_in_escrow:
        flash("Only transactions currently held in escrow can be disputed.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    try:
        txn.transition_to(TransactionStatus.disputed, db.session)
        
        # Record notification updates to both parties
        buyer_notify = Notification(
            user_id=txn.buyer_id,
            notification_type='bell',
            message=f"Transaction ID {txn.id} was flagged as DISPUTED. Campus Plug staff will reach out.",
            link=url_for('payments.dashboard')
        )
        seller_notify = Notification(
            user_id=txn.seller_id,
            notification_type='bell',
            message=f"Transaction ID {txn.id} was flagged as DISPUTED by buyer. Our team will mediate.",
            link=url_for('payments.dashboard')
        )
        db.session.add(buyer_notify)
        db.session.add(seller_notify)
        db.session.commit()
        
        flash("Transaction marked as disputed. Campus Plug mediators will review details shortly.", "warning")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error handling dispute flag: {e}")
        flash("An unexpected error occurred while processing the dispute. Our team has been notified.", "danger")
        
    return redirect(url_for('payments.dashboard'))


@payments_bp.route('/payments/refund/<int:transaction_id>', methods=['POST'])
@login_required
def refund_funds(transaction_id):
    txn = Transaction.query.get_or_404(transaction_id)
    
    # Authorize: Only buyer or admin
    is_buyer = (current_user.id == txn.buyer_id)
    is_admin = getattr(current_user, 'is_admin', False)
    
    if not is_buyer and not is_admin:
        flash("Only the buyer or an administrator can authorize payment refunds.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    if txn.status not in [TransactionStatus.held_in_escrow, TransactionStatus.disputed]:
        flash("Only payments held in escrow or actively disputed can be refunded.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    try:
        # Trigger Paystack Refund
        if txn.paystack_reference:
            initiate_paystack_refund(txn.paystack_reference)
            
        txn.transition_to(TransactionStatus.refunded, db.session)
        
        # Restore marketplace listing and freelance gig status
        if txn.listing:
            txn.listing.status = 'active'
        elif txn.gig:
            txn.gig.status = 'open'
            if txn.proposal:
                txn.proposal.status = 'pending'
                
        # Send notification to the buyer
        n_buyer = Notification(
            user_id=txn.buyer_id,
            notification_type='bell',
            message=f"Payment refund of GHS {txn.amount:.2f} has been processed and returned to your MoMo account.",
            link=url_for('payments.dashboard')
        )
        db.session.add(n_buyer)
        db.session.commit()
        
        flash("Refund executed successfully. GHS {:.2f} returned to payer's MoMo account via Paystack Gateway Refund.".format(txn.amount), "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error executing customer refund: {e}")
        flash("An unexpected error occurred while processing the refund. Our team has been notified.", "danger")
        
    return redirect(url_for('payments.dashboard'))


def credit_referral_reward(txn, session):
    """Credit a platform fee waiver to referrer for every 5 completed referrals."""
    try:
        for uid in [txn.buyer_id, txn.seller_id]:
            user = User.query.get(uid)
            if not user or not user.referred_by_id:
                continue
            # Check if this is their first completed transaction
            prior = Transaction.query.filter(
                Transaction.id != txn.id,
                (Transaction.buyer_id == user.id) | (Transaction.seller_id == user.id),
                Transaction.status == TransactionStatus.released
            ).count()
            if prior > 0:
                continue
            referrer = User.query.get(user.referred_by_id)
            if not referrer:
                continue
            referrer.completed_referral_count = (referrer.completed_referral_count or 0) + 1
            count = referrer.completed_referral_count
            if count % 5 == 0:
                referrer.pending_fee_waivers = (referrer.pending_fee_waivers or 0) + 1
                msg = f"Milestone reached! {user.full_name} completed their first transaction. You now have {referrer.pending_fee_waivers} platform fee waiver(s) — your next sale is fee-free!"
            else:
                msg = f"{user.full_name} completed their first transaction. You need {5 - (count % 5)} more completed referral(s) for your next fee waiver."
            notif = Notification(
                user_id=referrer.id,
                notification_type='bell',
                message=msg,
                link=url_for('auth.referrals')
            )
            session.add(notif)
    except Exception as e:
        current_app.logger.error(f"Error crediting referral reward: {e}")


def prompt_reviews_for_transaction(txn, session):
    """Creates dual bell notifications for both parties of a released transaction to leave peer reviews."""
    try:
        # Prompt buyer/payer to review seller
        n_buyer = Notification(
            user_id=txn.buyer_id,
            notification_type='bell',
            message=f"How did transaction #{txn.id} go? Please leave a rating and review for merchant {txn.seller.full_name}.",
            link=url_for('payments.submit_review', transaction_id=txn.id)
        )
        # Prompt merchant to review buyer/payer
        n_seller = Notification(
            user_id=txn.seller_id,
            notification_type='bell',
            message=f"How did transaction #{txn.id} go? Please leave a rating and review for student buyer {txn.buyer.full_name}.",
            link=url_for('payments.submit_review', transaction_id=txn.id)
        )
        session.add_all([n_buyer, n_seller])
        session.flush() # Ensure generated properly inside the database session block
    except Exception as e:
        # Prevent any notification failures from breaking core payment release transactions
        print(f"Non-blocking review notification creation failure: {e}")


@payments_bp.route('/payments/review/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def submit_review(transaction_id):
    txn = Transaction.query.get_or_404(transaction_id)
    
    # Authorizations check
    if current_user.id != txn.buyer_id and current_user.id != txn.seller_id:
        flash("You are not authorized to review this transaction.", "danger")
        return redirect(url_for('payments.dashboard'))
        
    if txn.status != TransactionStatus.released:
        flash("Escrow must be released before leaving a peer rating.", "warning")
        return redirect(url_for('payments.dashboard'))
        
    # Prevent duplicate reviews
    existing = Review.query.filter_by(transaction_id=txn.id, reviewer_id=current_user.id).first()
    if existing:
        flash("You have already submitted a rating for this transaction context.", "warning")
        return redirect(url_for('payments.dashboard'))
        
    # Identify target peer being rated
    reviewee_id = txn.seller_id if current_user.id == txn.buyer_id else txn.buyer_id
    reviewee = User.query.get_or_404(reviewee_id)
    
    if request.method == 'POST':
        try:
            rating_val = int(request.form.get('rating', 5))
            comment = request.form.get('comment', '').strip()
            
            if rating_val < 1 or rating_val > 5:
                flash("Please submit a rating between 1 and 5 stars.", "danger")
                return redirect(request.url)
                
            # Create the Review entry
            new_review = Review(
                transaction_id=txn.id,
                reviewer_id=current_user.id,
                reviewee_id=reviewee_id,
                rating=rating_val,
                comment=comment,
                created_at=datetime.utcnow()
            )
            db.session.add(new_review)
            db.session.commit()
            
            # Recalculate and update the cached values on the User model
            all_received_reviews = Review.query.filter_by(reviewee_id=reviewee_id).all()
            reviewee.review_count = len(all_received_reviews)
            if reviewee.review_count > 0:
                reviewee.avg_rating = sum(r.rating for r in all_received_reviews) / reviewee.review_count
            else:
                reviewee.avg_rating = 0.0
                
            # Let the peer know they got rated
            n_review = Notification(
                user_id=reviewee_id,
                notification_type='bell',
                message=f"Student rating notification! {current_user.full_name} has rated you {rating_val} stars on your trade.",
                link=url_for('marketplace.browse') # fallback or dashboard
            )
            db.session.add(n_review)
            db.session.commit()
            
            flash(f"Success! Your peer rating for {reviewee.full_name} has been processed successfully.", "success")
            return redirect(url_for('payments.dashboard'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to submit peer review rating: {e}")
            flash("An unexpected error occurred while submitting your review. Our team has been notified.", "danger")
            
    return render_template('payments/submit_review.html', txn=txn, reviewee=reviewee)
