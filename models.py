from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# Enums and Lists as standard lists for validation and dropdowns
UNIVERSITIES = [
    'University of Ghana',
    'KNUST',
    'University of Cape Coast',
    'GIMPA',
    'Ashesi University',
    'University of Education Winneba',
    'Central University',
    'Valley View University',
    'University of Professional Studies Accra (UPSA)',
    'Ghana Communication Technology University (GCTU)',
    'Other',
    'External / Business'
]

CATEGORIES = [
    'Textbooks',
    'Electronics',
    'Clothing & Fashion',
    'Furniture & Dorm Essentials',
    'Food & Snacks',
    'Beauty & Personal Care',
    'Sports & Fitness',
    'Other'
]

GIG_CATEGORIES = [
    'Tutoring & Academic Help',
    'Graphic Design',
    'Writing & Editing',
    'Web/App Development',
    'Photography & Videography',
    'Errands & Delivery',
    'Hair & Beauty Services',
    'Event Help',
    'Other'
]

CONDITIONS = [
    'Brand New',
    'Neatly Used',
    'Used',
    'Good'
]

DELIVERY_POLICIES = [
    'Campus Pickup Only',
    'Can Deliver Locally',
    'Ships Nationwide'
]

MOMO_PROVIDERS = [
    'MTN Mobile Money',
    'Telecel Cash',
    'AirtelTigo Money'
]

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    university = db.Column(db.String(100), nullable=False, default='Other')
    phone = db.Column(db.String(20), nullable=True)
    momo_provider = db.Column(db.String(50), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    avatar = db.Column(db.String(200), nullable=True) # URL or path to static image
    is_verified = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False, index=True)
    is_suspended = db.Column(db.Boolean, default=False, index=True)
    account_type = db.Column(db.String(20), default='regular', index=True)
    avg_rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    last_recommendation_at = db.Column(db.DateTime, nullable=True)
    password_reset_token = db.Column(db.String(200), nullable=True, index=True)
    password_reset_expires_at = db.Column(db.DateTime, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    location_name = db.Column(db.String(200), nullable=True)
    referral_code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    completed_referral_count = db.Column(db.Integer, default=0)
    pending_fee_waivers = db.Column(db.Integer, default=0)
    email_verified = db.Column(db.Boolean, default=False, nullable=True)
    email_verification_token = db.Column(db.String(200), nullable=True, index=True)
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=True)
    locked_until = db.Column(db.DateTime, nullable=True)
    last_seen = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    listings = db.relationship('Listing', back_populates='seller', cascade='all, delete-orphan')
    gigs = db.relationship('Gig', back_populates='client', cascade='all, delete-orphan')
    proposals = db.relationship('Proposal', back_populates='freelancer', cascade='all, delete-orphan')
    referred_by = db.relationship('User', remote_side='User.id', backref=db.backref('referrals', lazy='dynamic'))
    
    # Received and Authored reviews
    reviews_received = db.relationship('Review', foreign_keys='Review.reviewee_id', back_populates='reviewee', cascade='all, delete-orphan')
    reviews_authored = db.relationship('Review', foreign_keys='Review.reviewer_id', back_populates='reviewer', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_online(self):
        if not self.last_seen:
            return False
        return (datetime.utcnow() - self.last_seen).total_seconds() < 300

    @property
    def avatar_url(self):
        if self.avatar:
            if self.avatar.startswith(('http://', 'https://')):
                return self.avatar
            try:
                path = self.avatar.lstrip('/')
                full = os.path.join(os.getcwd(), path)
                mtime = int(os.path.getmtime(full)) if os.path.exists(full) else 0
                return f"{self.avatar}?v={mtime}"
            except Exception:
                pass
            return self.avatar
        return None

    @property
    def average_rating(self):
        if self.review_count and self.review_count > 0:
            return round(self.avg_rating, 1)
        reviews = self.reviews_received
        if not reviews:
            return None
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

class Listing(db.Model):
    __tablename__ = 'listings'
    
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Float, nullable=False)  # Current (discounted) price in GHS
    original_price = db.Column(db.Float, nullable=True)  # Pre-discount price
    discount_percent = db.Column(db.Integer, nullable=True)  # e.g. 15 for 15% off
    category = db.Column(db.String(50), nullable=False, index=True)
    condition = db.Column(db.String(50), nullable=False)  # Brand New, Neatly Used, Used, Good
    university = db.Column(db.String(100), nullable=False, index=True) # Seller university
    delivery_policy = db.Column(db.String(50), nullable=False, default='Campus Pickup Only')
    is_negotiable = db.Column(db.Boolean, default=False)
    quantity = db.Column(db.Integer, default=1)
    photos = db.Column(db.Text, nullable=True)  # Comma-separated list of image paths
    status = db.Column(db.String(20), default='active', index=True)  # active, sold, deleted
    removed_by_admin = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    seller = db.relationship('User', back_populates='listings')
    transactions = db.relationship('Transaction', back_populates='listing')

    @property
    def photo_list(self):
        if not self.photos:
            return ['/static/images/placeholder.jpg']
        return [p.strip() for p in self.photos.split(',') if p.strip()]

    @property
    def is_sold_out(self):
        return self.quantity is not None and self.quantity <= 0

    @property
    def has_discount(self):
        return self.original_price is not None and self.original_price > self.price

    @property
    def fee_details(self):
        # 10% Platform fee calculation
        fee = round(self.price * 0.10, 2)
        payout = round(self.price - fee, 2)
        return {
            'fee': fee,
            'payout': payout
        }

    @property
    def discount_saved(self):
        if not self.has_discount:
            return 0
        return round(self.original_price - self.price, 2)

class Gig(db.Model):
    __tablename__ = 'gigs'
    
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    budget = db.Column(db.Float, nullable=False)  # Budget or max budget in GHS
    budget_min = db.Column(db.Float, nullable=True) # Optional minimum budget in GHS
    budget_type = db.Column(db.String(20), default='fixed') # fixed, range
    deadline = db.Column(db.String(50), nullable=True) # User-defined date or deadline
    category = db.Column(db.String(50), nullable=False, default='Other', index=True)
    university = db.Column(db.String(100), nullable=False, index=True) # Poster university
    remote_friendly = db.Column(db.Boolean, default=True) # True = Remote friendly, False = Local only
    location_type = db.Column(db.String(100), default='Remote — any university') # Remote — any university, On-campus — specific university
    status = db.Column(db.String(20), default='open', index=True)  # open, assigned (or in_progress), completed, cancelled
    removed_by_admin = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    client = db.relationship('User', back_populates='gigs')
    proposals = db.relationship('Proposal', back_populates='gig', cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', back_populates='gig')

class Proposal(db.Model):
    __tablename__ = 'proposals'
    
    id = db.Column(db.Integer, primary_key=True)
    gig_id = db.Column(db.Integer, db.ForeignKey('gigs.id'), nullable=False, index=True)
    freelancer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    price = db.Column(db.Float, nullable=False)  # Bid price in GHS
    delivery_time = db.Column(db.String(100), nullable=True) # "3 days", "1 week" etc.
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(25), default='pending', index=True)  # pending, accepted, rejected/declined
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    gig = db.relationship('Gig', back_populates='proposals')
    freelancer = db.relationship('User', back_populates='proposals')

class Offer(db.Model):
    __tablename__ = 'offers'

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    price = db.Column(db.Float, nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, countered, declined
    seller_note = db.Column(db.Text, nullable=True)  # seller's counter/response note
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    listing = db.relationship('Listing', backref=db.backref('offers', cascade='all, delete-orphan'))
    buyer = db.relationship('User', backref=db.backref('offers', cascade='all, delete-orphan'))

class CartItem(db.Model):
    __tablename__ = 'cart_items'

    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=False, index=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buyer = db.relationship('User', backref=db.backref('cart_items', cascade='all, delete-orphan'))
    listing = db.relationship('Listing')

    __table_args__ = (
        db.UniqueConstraint('buyer_id', 'listing_id', name='uq_buyer_listing_cart'),
    )

    @property
    def total_price(self):
        return self.listing.price * self.quantity

class Message(db.Model):
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=True, index=True)
    gig_id = db.Column(db.Integer, db.ForeignKey('gigs.id'), nullable=True, index=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])

import enum

class TransactionStatus(enum.Enum):
    pending_payment = 'pending_payment'
    held_in_escrow = 'held_in_escrow'
    released = 'released'
    refunded = 'refunded'
    disputed = 'disputed'

class Transaction(db.Model):
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    context_type = db.Column(db.String(20), nullable=False) # 'listing' or 'gig'
    context_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Optional direct references for SQLAlchemy compatibility with listing / gig templates
    listing_id = db.Column(db.Integer, db.ForeignKey('listings.id'), nullable=True)
    gig_id = db.Column(db.Integer, db.ForeignKey('gigs.id'), nullable=True)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposals.id'), nullable=True)
    
    amount = db.Column(db.Float, nullable=False)              # The full amount buyer paid/pays (in GHS)
    platform_fee = db.Column(db.Float, nullable=False)        # Always 10%
    seller_payout_amount = db.Column(db.Float, nullable=False) # amount - platform_fee
    
    status = db.Column(db.Enum(TransactionStatus), nullable=False, default=TransactionStatus.pending_payment, index=True)
    
    paystack_reference = db.Column(db.String(100), unique=True, nullable=True)
    paystack_transfer_code = db.Column(db.String(100), nullable=True)

    bulk_items = db.Column(db.JSON, nullable=True)  # [{"listing_id": N, "title": "...", "price": N, "quantity": N}, ...]
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    released_at = db.Column(db.DateTime, nullable=True)
    auto_release_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    buyer = db.relationship('User', foreign_keys=[buyer_id], backref=db.backref('purchases_momo', lazy='dynamic'))
    seller = db.relationship('User', foreign_keys=[seller_id], backref=db.backref('sales_momo', lazy='dynamic'))
    listing = db.relationship('Listing', back_populates='transactions')
    gig = db.relationship('Gig', back_populates='transactions')
    proposal = db.relationship('Proposal', foreign_keys=[proposal_id])

    @property
    def payout_amount(self):
        return self.seller_payout_amount

    def transition_to(self, new_status, session):
        """Helper to change state and automatically write state transition audits."""
        old_status_val = self.status.value if hasattr(self.status, 'value') else str(self.status)
        new_status_enum = new_status if isinstance(new_status, TransactionStatus) else TransactionStatus[new_status]
        self.status = new_status_enum
        
        log = TransactionLog(
            transaction_id=self.id,
            old_status=old_status_val,
            new_status=new_status_enum.value,
            changed_at=datetime.utcnow()
        )
        session.add(log)

class TransactionLog(db.Model):
    __tablename__ = 'transaction_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=False)
    old_status = db.Column(db.String(50), nullable=True)
    new_status = db.Column(db.String(50), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    transaction = db.relationship('Transaction', backref=db.backref('logs', cascade='all, delete-orphan'))

class Review(db.Model):
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reviewee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1 to 5 Stars
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reviewer = db.relationship('User', foreign_keys=[reviewer_id], back_populates='reviews_authored')
    reviewee = db.relationship('User', foreign_keys=[reviewee_id], back_populates='reviews_received')
    transaction = db.relationship('Transaction', backref=db.backref('reviews', cascade='all, delete-orphan'))

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    notification_type = db.Column(db.String(50), nullable=False) # e.g., 'proposal', 'accepted', 'message', 'sold'
    message = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id])

class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action = db.Column(db.String(255), nullable=False) # e.g., 'suspend_user', 'remove_listing', 'resolve_dispute'
    target_id = db.Column(db.Integer, nullable=True) # ID of target user, listing, gig, or transaction
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    admin = db.relationship('User', foreign_keys=[admin_id])

class ShowcasePost(db.Model):
    __tablename__ = 'showcase_posts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    media_url = db.Column(db.String(255), nullable=True) # Single photo path (legacy)
    media_urls = db.Column(db.Text, nullable=True) # Comma-separated photo paths
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    freelancer = db.relationship('User', backref=db.backref('showcases', cascade='all, delete-orphan'))
    likes = db.relationship('ShowcaseLike', back_populates='post', cascade='all, delete-orphan')
    comments = db.relationship('ShowcaseComment', back_populates='post', cascade='all, delete-orphan')

    @property
    def media_list(self):
        if self.media_urls:
            return [u.strip() for u in self.media_urls.split(',') if u.strip()]
        if self.media_url:
            return [self.media_url]
        return []

class ShowcaseLike(db.Model):
    __tablename__ = 'showcase_likes'
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('showcase_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    post = db.relationship('ShowcasePost', back_populates='likes')
    user = db.relationship('User', backref=db.backref('liked_showcases', cascade='all, delete-orphan'))

class ShowcaseComment(db.Model):
    __tablename__ = 'showcase_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('showcase_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    post = db.relationship('ShowcasePost', back_populates='comments')
    user = db.relationship('User', backref=db.backref('showcase_comments', cascade='all, delete-orphan'))


def get_top_seller_ids(limit=10):
    """Return list of user IDs for top sellers by sales, volume, and rating.
    
    Uses aggregate subqueries — 3 queries total instead of 1 + 3N.
    """
    from sqlalchemy import func
    
    sales_agg = db.session.query(
        Transaction.seller_id,
        func.count(Transaction.id).label('sales_count'),
        func.sum(Transaction.amount).label('sales_volume')
    ).filter(
        Transaction.status == TransactionStatus.released
    ).group_by(Transaction.seller_id).subquery()
    
    rating_agg = db.session.query(
        Review.reviewee_id,
        func.avg(Review.rating).label('avg_rating')
    ).group_by(Review.reviewee_id).subquery()
    
    sellers = User.query.filter(
        User.account_type.in_(['seller', 'admin']),
        User.is_suspended == False
    ).outerjoin(
        sales_agg, sales_agg.c.seller_id == User.id
    ).outerjoin(
        rating_agg, rating_agg.c.reviewee_id == User.id
    ).with_entities(
        User.id,
        func.coalesce(sales_agg.c.sales_count, 0).label('completed'),
        func.coalesce(sales_agg.c.sales_volume, 0).label('volume'),
        func.coalesce(rating_agg.c.avg_rating, 0).label('rating'),
    ).all()
    
    scored = [(row.id, row.completed * 10 + float(row.volume) + float(row.rating) * 5) for row in sellers]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [sid for sid, _ in scored[:limit]]


def generate_referral_code():
    """Generate a unique 8-char uppercase referral code."""
    import secrets
    import string
    while True:
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        if not User.query.filter_by(referral_code=code).first():
            return code

