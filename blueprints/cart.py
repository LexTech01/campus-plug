from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from models import db, CartItem, Listing, Notification
from datetime import datetime

cart_bp = Blueprint('cart', __name__)

@cart_bp.route('/cart')
@login_required
def view_cart():
    items = CartItem.query.filter_by(buyer_id=current_user.id)\
        .order_by(CartItem.created_at.desc()).all()
    
    # Group by seller
    seller = None
    seller_items = []
    total = 0
    for item in items:
        listing = item.listing
        if listing and listing.status == 'active' and not listing.is_sold_out:
            if not seller:
                seller = listing.seller
            seller_items.append(item)
            total += item.total_price
    
    return render_template('cart/cart.html',
        items=seller_items, seller=seller, total=total)

@cart_bp.route('/cart/add/<int:listing_id>', methods=['POST'])
@login_required
def add_to_cart(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    if listing.seller_id == current_user.id:
        flash("You cannot add your own listing to cart.", 'warning')
        return redirect(request.referrer or url_for('marketplace.detail', listing_id=listing_id))
    
    if listing.status != 'active' or listing.is_sold_out:
        flash("This item is no longer available.", 'danger')
        return redirect(request.referrer or url_for('marketplace.browse'))
    
    # Check if cart already has items from a different seller
    existing = CartItem.query.filter_by(buyer_id=current_user.id).first()
    if existing and existing.listing.seller_id != listing.seller_id:
        flash("You can only buy from one seller at a time. Please checkout or clear your cart first.", 'warning')
        return redirect(request.referrer or url_for('marketplace.detail', listing_id=listing_id))
    
    cart_item = CartItem.query.filter_by(buyer_id=current_user.id, listing_id=listing_id).first()
    if cart_item:
        cart_item.quantity += 1
        flash(f"Increased quantity of \"{listing.title}\" in your cart.", 'success')
    else:
        cart_item = CartItem(buyer_id=current_user.id, listing_id=listing_id, quantity=1)
        db.session.add(cart_item)
        flash(f"\"{listing.title}\" added to cart.", 'success')
    
    db.session.commit()
    return redirect(request.referrer or url_for('marketplace.detail', listing_id=listing_id))

@cart_bp.route('/cart/remove/<int:item_id>', methods=['POST'])
@login_required
def remove_from_cart(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.buyer_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    db.session.delete(item)
    db.session.commit()
    flash("Item removed from cart.", 'success')
    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/cart/update/<int:item_id>', methods=['POST'])
@login_required
def update_cart(item_id):
    item = CartItem.query.get_or_404(item_id)
    if item.buyer_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    quantity = request.form.get('quantity', type=int)
    if quantity and quantity > 0 and quantity <= 99:
        item.quantity = quantity
        db.session.commit()
        flash("Cart updated.", 'success')
    else:
        flash("Invalid quantity.", 'warning')
    
    return redirect(url_for('cart.view_cart'))

@cart_bp.route('/cart/clear', methods=['POST'])
@login_required
def clear_cart():
    CartItem.query.filter_by(buyer_id=current_user.id).delete()
    db.session.commit()
    flash("Cart cleared.", 'success')
    return redirect(url_for('cart.view_cart'))
