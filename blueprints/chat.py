from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from models import db, User, Message, Listing, Gig, Notification
from sqlalchemy import or_, and_
from datetime import datetime
from utils import rate_limit

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/chat')
@chat_bp.route('/inbox')
@login_required
def inbox():
    # Fetch all messages involving the current user
    all_msgs = Message.query.filter(
        or_(Message.sender_id == current_user.id, Message.recipient_id == current_user.id)
    ).order_by(Message.created_at.desc()).limit(500).all()
    
    unique_conversations = {} # Key: (other_user_id, context_type, context_id)
    
    for m in all_msgs:
        other_user_id = m.recipient_id if m.sender_id == current_user.id else m.sender_id
        context_type = 'listing' if m.listing_id else ('gig' if m.gig_id else 'general')
        context_id = m.listing_id if m.listing_id else (m.gig_id if m.gig_id else None)
        
        key = (other_user_id, context_type, context_id)
        if key not in unique_conversations:
            unique_conversations[key] = []
        unique_conversations[key].append(m)
        
    threads = []
    for (other_user_id, context_type, context_id), msgs in unique_conversations.items():
        other_user = User.query.get(other_user_id)
        if not other_user:
            continue
            
        # Get latest message
        last_msg = msgs[0] # Order is desc, so first is latest
        
        # Count unread messages in this thread
        unread_count = sum(1 for m in msgs if m.recipient_id == current_user.id and not m.is_read)
        
        # Get context title
        context_title = ""
        context_link = ""
        if context_type == 'listing' and context_id:
            listing = Listing.query.get(context_id)
            if listing:
                context_title = f"Listing: {listing.title}"
                context_link = url_for('marketplace.detail', listing_id=listing.id)
        elif context_type == 'gig' and context_id:
            gig = Gig.query.get(context_id)
            if gig:
                context_title = f"Gig: {gig.title}"
                context_link = url_for('freelance.detail', gig_id=gig.id)
                
        threads.append({
            'other_user': other_user,
            'context_type': context_type,
            'context_id': context_id,
            'context_title': context_title,
            'context_link': context_link,
            'last_message': last_msg,
            'unread_count': unread_count
        })
        
    # Sort threads by latest message timestamp
    threads.sort(key=lambda t: t['last_message'].created_at if t['last_message'] else datetime.min, reverse=True)
    
    # Check if we want to auto-redirect to initiate a specific chat via query args
    with_user_id = request.args.get('with_user', type=int)
    init_context_type = request.args.get('context_type', '')
    init_context_id = request.args.get('context_id', type=int)
    
    if with_user_id:
        return redirect(url_for('chat.thread_view', 
                                other_id=with_user_id, 
                                context_type=init_context_type, 
                                context_id=init_context_id))
        
    return render_template('chat/list.html', threads=threads)


@chat_bp.route('/chat/thread/<int:other_id>', methods=['GET'])
@login_required
def thread_view(other_id):
    other_user = User.query.get_or_404(other_id)
    context_type = request.args.get('context_type', 'general')
    context_id = request.args.get('context_id', type=int)
    
    # Fetch messages in this specific thread
    query = Message.query.filter(
        or_(
            and_(Message.sender_id == current_user.id, Message.recipient_id == other_id),
            and_(Message.sender_id == other_id, Message.recipient_id == current_user.id)
        )
    )
    
    # Filter by context
    if context_type == 'listing' and context_id:
        query = query.filter_by(listing_id=context_id)
    elif context_type == 'gig' and context_id:
        query = query.filter_by(gig_id=context_id)
    else:
        query = query.filter(Message.listing_id == None, Message.gig_id == None)
        
    messages = query.order_by(Message.created_at.asc()).all()
    
    # Mark messages in this thread read
    unread_messages = [m for m in messages if m.recipient_id == current_user.id and not m.is_read]
    for m in unread_messages:
        m.is_read = True
    if unread_messages:
        db.session.commit()
        
    # Get context details for the top bar
    context_item = None
    if context_type == 'listing' and context_id:
        context_item = Listing.query.get(context_id)
    elif context_type == 'gig' and context_id:
        context_item = Gig.query.get(context_id)
        
    return render_template('chat/thread.html',
                           other_user=other_user,
                           messages=messages,
                           context_type=context_type,
                           context_id=context_id,
                           context_item=context_item)


@chat_bp.route('/chat/send', methods=['POST'])
@login_required
@rate_limit('send_message', max_attempts=20, window=60)
def send_message():
    recipient_id = request.form.get('recipient_id', type=int)
    body = request.form.get('body', '').strip()
    context_type = request.form.get('context_type', 'general')
    context_id = request.form.get('context_id', type=int)
    
    if not recipient_id or not body:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
            return jsonify({'success': False, 'error': 'Missing fields'}), 400
        flash('Cannot send empty message.', 'danger')
        return redirect(url_for('chat.inbox'))
        
    recipient = User.query.get_or_404(recipient_id)
    
    # Map context
    listing_id = context_id if context_type == 'listing' else None
    gig_id = context_id if context_type == 'gig' else None
    
    new_msg = Message(
        sender_id=current_user.id,
        recipient_id=recipient.id,
        body=body,
        listing_id=listing_id,
        gig_id=gig_id
    )
    db.session.add(new_msg)
    
    # In-app Notification row trigger
    n = Notification(
        user_id=recipient.id,
        notification_type='message',
        message=f"New message from {current_user.full_name}",
        link=url_for('chat.thread_view', other_id=current_user.id, context_type=context_type, context_id=context_id)
    )
    db.session.add(n)
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({
            'success': True,
            'message': {
                'id': new_msg.id,
                'sender_id': new_msg.sender_id,
                'recipient_id': new_msg.recipient_id,
                'body': new_msg.body,
                'created_at': new_msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            }
        })
        
    return redirect(url_for('chat.thread_view', other_id=recipient.id, context_type=context_type, context_id=context_id))


@chat_bp.route('/chat/thread/<int:other_id>/messages')
@login_required
def get_messages(other_id):
    context_type = request.args.get('context_type', 'general')
    context_id = request.args.get('context_id', type=int)
    last_id = request.args.get('last_id', 0, type=int)
    
    query = Message.query.filter(
        or_(
            and_(Message.sender_id == current_user.id, Message.recipient_id == other_id),
            and_(Message.sender_id == other_id, Message.recipient_id == current_user.id)
        )
    )
    
    if context_type == 'listing' and context_id:
        query = query.filter_by(listing_id=context_id)
    elif context_type == 'gig' and context_id:
        query = query.filter_by(gig_id=context_id)
    else:
        query = query.filter(Message.listing_id == None, Message.gig_id == None)
        
    if last_id > 0:
        query = query.filter(Message.id > last_id)
        
    new_messages = query.order_by(Message.created_at.asc()).all()
    
    # Mark as read on poll retrieval
    unread_any = False
    for m in new_messages:
        if m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True
            unread_any = True
    if unread_any:
        db.session.commit()
        
    data = []
    for m in new_messages:
        data.append({
            'id': m.id,
            'sender_id': m.sender_id,
            'recipient_id': m.recipient_id,
            'body': m.body,
            'created_at': m.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_read': m.is_read
        })
    return jsonify({'messages': data, 'current_user_id': current_user.id})
