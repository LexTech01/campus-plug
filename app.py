import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template,redirect, url_for, flash, jsonify
from flask_login import LoginManager
try:
    from flask_migrate import Migrate, upgrade
    HAS_MIGRATE = True
except ImportError:
    Migrate = None
    upgrade = None
    HAS_MIGRATE = False
from extensions import csrf
from config import DevelopmentConfig, ProductionConfig, Config
from models import db, User, Listing, Gig, Proposal, Message, Transaction, Review, Notification, ShowcasePost, ShowcaseLike, ShowcaseComment, generate_referral_code

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'warning'



@login_manager.user_loader
def load_user(user_id):
    user = User.query.get(int(user_id))
    if user and user.is_suspended:
        return None
    return user

def create_app():
    app = Flask(__name__)
    if os.environ.get('FLASK_ENV') == 'production':
        app.config.from_object(ProductionConfig)
    else:
        app.config.from_object(DevelopmentConfig)

    # Validate config — abort in production if critical vars missing
    config_errors = Config.validate(production=not app.debug)
    for err in config_errors:
        app.logger.warning(f"Config: {err}")

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Production logging
    if not app.debug:
        os.makedirs('logs', exist_ok=True)
        handler = RotatingFileHandler('logs/campus_plug.log', maxBytes=10*1024*1024, backupCount=5)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s'))
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('Campus Plug starting')

    # Security headers
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        csp = app.config.get('CONTENT_SECURITY_POLICY')
        if csp:
            directives = []
            for key, val in csp.items():
                if isinstance(val, list):
                    val = ' '.join(val)
                directives.append(f"{key} {val}")
            response.headers['Content-Security-Policy'] = '; '.join(directives)
        return response

    # Initialize extensions
    db.init_app(app)
    if HAS_MIGRATE:
        Migrate(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register blueprints
    from blueprints.auth import auth_bp
    from blueprints.marketplace import marketplace_bp
    from blueprints.freelance import freelance_bp
    from blueprints.chat import chat_bp
    from blueprints.payments import payments_bp
    from blueprints.admin import admin_bp
    from blueprints.map import map_bp
    from blueprints.cart import cart_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(freelance_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(cart_bp)

    # Custom context processors/filters for Jinja2
    @app.context_processor
    def inject_globals():
        from models import UNIVERSITIES, CATEGORIES, CONDITIONS, DELIVERY_POLICIES, MOMO_PROVIDERS, GIG_CATEGORIES, Notification, Message, CartItem
        from flask_login import current_user
        unread_notifications_count = 0
        unread_messages_count = 0
        recent_notifications = []
        cart_count = 0
        if current_user.is_authenticated:
            unread_notifications_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
            unread_messages_count = Message.query.filter_by(recipient_id=current_user.id, is_read=False).count()
            recent_notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
            cart_count = CartItem.query.filter_by(buyer_id=current_user.id).count()
        import time as _time
        return {
            'UNIVERSITIES': UNIVERSITIES,
            'CATEGORIES': CATEGORIES,
            'CONDITIONS': CONDITIONS,
            'DELIVERY_POLICIES': DELIVERY_POLICIES,
            'MOMO_PROVIDERS': MOMO_PROVIDERS,
            'GIG_CATEGORIES': GIG_CATEGORIES,
            'unread_notifications_count': unread_notifications_count,
            'unread_messages_count': unread_messages_count,
            'recent_notifications': recent_notifications,
            'cart_count': cart_count,
            'SUPPORT_EMAIL': 'campusplug30@gmail.com',
            'cache_buster': int(_time.time()),
        }

    # Root route - Landing page
    @app.route('/')
    def index():
        # Get trending listings (first 4)
        trending_listings = Listing.query.filter_by(status='active', removed_by_admin=False).order_by(Listing.created_at.desc()).limit(4).all()
        # Get featured gigs (first 3)
        featured_gigs = Gig.query.filter_by(status='open', removed_by_admin=False).order_by(Gig.created_at.desc()).limit(3).all()
        
        return render_template('index.html', listings=trending_listings, gigs=featured_gigs)

    @app.route('/terms')
    def terms():
        return render_template('terms.html')

    @app.route('/leaderboard')
    def leaderboard():
        from models import Transaction, TransactionStatus, Review, Listing
        from sqlalchemy import func
        
        # Aggregate subqueries — 3 queries total instead of 1 + 3N
        sales_agg = db.session.query(
            Transaction.seller_id,
            func.count(Transaction.id).label('completed_sales'),
            func.sum(Transaction.amount).label('total_volume')
        ).filter(
            Transaction.status == TransactionStatus.released
        ).group_by(Transaction.seller_id).subquery()
        
        rating_agg = db.session.query(
            Review.reviewee_id,
            func.avg(Review.rating).label('avg_rating')
        ).group_by(Review.reviewee_id).subquery()
        
        listing_agg = db.session.query(
            Listing.seller_id,
            func.count(Listing.id).label('active_listings')
        ).filter(
            Listing.status == 'active',
            Listing.removed_by_admin == False
        ).group_by(Listing.seller_id).subquery()
        
        sellers = User.query.filter(
            User.account_type.in_(['seller', 'admin']),
            User.is_suspended == False
        ).outerjoin(
            sales_agg, sales_agg.c.seller_id == User.id
        ).outerjoin(
            rating_agg, rating_agg.c.reviewee_id == User.id
        ).outerjoin(
            listing_agg, listing_agg.c.seller_id == User.id
        ).with_entities(
            User,
            func.coalesce(sales_agg.c.completed_sales, 0).label('cs'),
            func.coalesce(sales_agg.c.total_volume, 0).label('tv'),
            func.coalesce(rating_agg.c.avg_rating, 0).label('ar'),
            func.coalesce(listing_agg.c.active_listings, 0).label('al'),
        ).all()
        
        leaderboard_data = []
        for row in sellers:
            completed_sales = int(row.cs)
            total_volume = float(row.tv)
            active_listings = int(row.al)
            avg_rating = float(row.ar)
            score = completed_sales * 10 + total_volume + avg_rating * 5
            leaderboard_data.append({
                'seller': row.User,
                'completed_sales': completed_sales,
                'total_volume': round(total_volume, 2),
                'active_listings': active_listings,
                'avg_rating': round(avg_rating, 1) if avg_rating else None,
                'review_count': row.User.review_count or 0,
                'score': round(score, 2)
            })
        
        leaderboard_data.sort(key=lambda x: x['score'], reverse=True)
        for i, entry in enumerate(leaderboard_data):
            entry['rank'] = i + 1
        
        return render_template('leaderboard.html', leaderboard=leaderboard_data)

    # Error Handlers
    @app.errorhandler(400)
    def bad_request_error(e):
        return render_template('errors/400.html', error=str(e)), 400

    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(413)
    def payload_too_large(e):
        flash('File too large. Maximum size is 20 MB.', 'danger')
        return redirect(request.referrer or url_for('index'))

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/500.html'), 500

    # Favicon
    @app.route('/favicon.ico')
    def favicon():
        from flask import send_from_directory
        return send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

    # Health check
    @app.route('/health')
    def health():
        try:
            db.session.execute(db.text('SELECT 1'))
            # Auto-release expired escrow (runs at most every 15 min)
            import tempfile, os as _os
            _lock = _os.path.join(tempfile.gettempdir(), 'campus_plug_autorelease')
            _now = __import__('time').time()
            _last = float(_os.popen(f'cat {_lock} 2>/dev/null || echo 0').read().strip() or 0)
            if _now - _last > 900:
                _os.system(f'echo {_now} > {_lock}')
                try:
                    from blueprints.payments import auto_release_expired_transactions
                    auto_release_expired_transactions()
                except Exception as ae:
                    app.logger.error(f"Auto-release: {ae}")
            return jsonify({'status': 'healthy', 'database': 'ok'})
        except Exception as e:
            return jsonify({'status': 'unhealthy', 'database': str(e)}), 500

    # Create Database and Seed if empty
    with app.app_context():
        if os.environ.get('SKIP_DB_CREATE') != '1':
            if HAS_MIGRATE and upgrade:
                try:
                    upgrade()
                except Exception as exc:
                    app.logger.error("Migration failed, falling back to create_all: %s", exc)
                    db.create_all()
            else:
                db.create_all()
            if app.config.get('DEBUG', False):
                seed_data()

    return app

def seed_data():
    if User.query.first() is not None:
        return # Database already seeded
    
    print("Database is empty. Seeding realistic Ghana Campus Plug data...")
    
    # 1. Create Seed Users with safe passwords
    u1 = User(
        email="yaw@knust.edu.gh",
        full_name="Yaw Boateng",
        university="KNUST",
        phone="0241234567",
        momo_provider="MTN Mobile Money",
        bio="Final year Computer Science student. Selling my standard hostel items and doing website gigs on weekends.",
        avatar="https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=200&q=80",
        is_verified=True,
        account_type='seller',
        referral_code=generate_referral_code(),
        latitude=6.6736,
        longitude=-1.5716,
        location_name='KNUST Campus, Kumasi'
    )
    u1.password_hash = "scrypt:32768:8:1$TTLpP1eEOipRQTqC$cd502b4bc514d2d8218f3801a21e7fb8d50362bc8b3dcfc5ce0ef841c79655a7ada1251723876f898e608b53c7a5e9d1790fee78cb944975ebdd5d0a947c5c1e"
    
    u2 = User(
        email="abena@ug.edu.gh",
        full_name="Abena Osei",
        university="University of Ghana",
        phone="0209876543",
        momo_provider="Telecel Cash",
        bio="Visual Arts Major. Enthusiastic about fashion, thrift items, and freelance graphic design.",
        avatar="https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=200&q=80",
        is_verified=True,
        account_type='seller',
        referral_code=generate_referral_code(),
        latitude=5.6503,
        longitude=-0.1871,
        location_name='University of Ghana, Legon'
    )
    u2.password_hash = "scrypt:32768:8:1$TTLpP1eEOipRQTqC$cd502b4bc514d2d8218f3801a21e7fb8d50362bc8b3dcfc5ce0ef841c79655a7ada1251723876f898e608b53c7a5e9d1790fee78cb944975ebdd5d0a947c5c1e"
    
    u3 = User(
        email="ernest@ashesi.edu.gh",
        full_name="Ernest Mensah",
        university="Ashesi University",
        phone="0551122334",
        momo_provider="MTN Mobile Money",
        bio="Business Administration undergrad. Always ready to tutor accounting or run errand services on campus.",
        avatar="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=200&q=80",
        is_verified=True,
        account_type='seller',
        referral_code=generate_referral_code(),
        latitude=5.7567,
        longitude=-0.2066,
        location_name='Ashesi University, Berekuso'
    )
    u3.password_hash = "scrypt:32768:8:1$TTLpP1eEOipRQTqC$cd502b4bc514d2d8218f3801a21e7fb8d50362bc8b3dcfc5ce0ef841c79655a7ada1251723876f898e608b53c7a5e9d1790fee78cb944975ebdd5d0a947c5c1e"

    u4 = User(
        email="esi@ucc.edu.gh",
        full_name="Esi Ampah",
        university="University of Cape Coast",
        phone="0276655443",
        momo_provider="AirtelTigo Money",
        bio="Economics student. Keen buyer of novels, reference textbooks, and dorm utilities.",
        avatar="https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=200&q=80",
        is_verified=True,
        referral_code=generate_referral_code()
    )
    u4.password_hash = "scrypt:32768:8:1$TTLpP1eEOipRQTqC$cd502b4bc514d2d8218f3801a21e7fb8d50362bc8b3dcfc5ce0ef841c79655a7ada1251723876f898e608b53c7a5e9d1790fee78cb944975ebdd5d0a947c5c1e"

    u5 = User(
        email="alexanderwinfred17@gmail.com",
        full_name="Alexander Winfred",
        university="University of Ghana",
        phone="0241112223",
        momo_provider="MTN Mobile Money",
        account_type='admin',
        bio="Lead Admin for Campus Plug Ghana. Feel free to contact me for disputes and support.",
        avatar="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=200&q=80",
        is_verified=True,
        is_admin=True,
        referral_code=generate_referral_code()
    )
    u5.password_hash = "scrypt:32768:8:1$J64MXkphnToFrgoF$7b7bbffe34dc5197513a18a8d549cc3fa7be1d456cfdb54080b9604e1c102e1499c9249f23797c851a03a6365fe86e891e80c07a35df613880b66d7b13ef1dd7"

    db.session.add_all([u1, u2, u3, u4, u5])
    db.session.commit() # Commit users so we can link foreign keys

    # 2. Create Seed Listings (Seller-to-student peer-marketplace items)
    l1 = Listing(
        seller_id=u1.id,
        title="Apple iPhone 12 Pro (256GB)",
        description="Selling my iPhone 12 Pro, midnight blue color. Factory unlocked, 86% battery health. Comes with original box and a premium fast-charging cable. Excellent performance for coursework and taking crisp campus photos.",
        price=3200.0,
        category="Electronics",
        condition="Neatly Used",
        university="KNUST",
        delivery_policy="Can Deliver Locally",
        photos="https://images.unsplash.com/photo-1510557880182-3d4d3cba35a5?auto=format&fit=crop&w=600&q=80",
        status="active"
    )

    l2 = Listing(
        seller_id=u2.id,
        title="Retro Over-the-Ear Headphones",
        description="Beige retro design, immersive sound quality and superb bass. Perfect for studying at the Balme Library. Selling because I upgraded to ANC earbuds. Bluetooth connected with 20h battery life.",
        price=450.0,
        category="Electronics",
        condition="Good",
        university="University of Ghana",
        delivery_policy="Campus Pickup Only",
        photos="https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=600&q=80",
        status="active"
    )

    l3 = Listing(
        seller_id=u3.id,
        title="Microeconomics & Statistics Textbook Bundle",
        description="Original core textbooks for freshman and sophomore business majors at Ashesi. No highlighting, virtually pristine condition. This bundle saves you over GHS 300 compared to buying from store.",
        price=200.0,
        category="Textbooks",
        condition="Good",
        university="Ashesi University",
        delivery_policy="Ships Nationwide",
        photos="https://images.unsplash.com/photo-1497633762265-9d179a990aa6?auto=format&fit=crop&w=600&q=80",
        status="active"
    )

    l4 = Listing(
        seller_id=u2.id,
        title="Thrift Baggy Denim Jeans & Cargo Pants Combo",
        description="Two high-quality baggy bottoms perfect for standard uni fits. Size 32 waist. Soft quality cotton denim, comfortable and strictly drip-certified.",
        price=180.0,
        category="Clothing & Fashion",
        condition="Good",
        university="University of Ghana",
        delivery_policy="Campus Pickup Only",
        photos="https://images.unsplash.com/photo-1541099649105-f69ad21f3246?auto=format&fit=crop&w=600&q=80",
        status="active"
    )

    l5 = Listing(
        seller_id=u1.id,
        title="Wooden 3-Tier Study Table Organizer",
        description="Hostel room essentials! Beautiful wooden organizer for organizing notebooks, stationery, and headphones. Compact, extremely lightweight, fits standard KNUST hostel tables flawlessly.",
        price=120.0,
        category="Furniture & Dorm Essentials",
        condition="Brand New",
        university="KNUST",
        delivery_policy="Campus Pickup Only",
        photos="https://images.unsplash.com/photo-1585776245991-cf89dd7fc73a?auto=format&fit=crop&w=600&q=80",
        status="active"
    )

    l6 = Listing(
        seller_id=u4.id,
        title="Adjustable Metal LED Desk Lamp",
        description="Sturdy metal reading lamp with adjustable arm. Cool and warm light modes. Powered by USB. Bought 3 months ago. Highly reliable for night study during UCC quiz weeks.",
        price=85.0,
        category="Furniture & Dorm Essentials",
        condition="Neatly Used",
        university="University of Cape Coast",
        delivery_policy="Campus Pickup Only",
        photos="https://images.unsplash.com/photo-1507473885765-e6ed057f782c?auto=format&fit=crop&w=600&q=80",
        status="active"
    )

    db.session.add_all([l1, l2, l3, l4, l5, l6])

    # 3. Create Seed Gigs (Freelance/Gig work for students)
    g1 = Gig(
        client_id=u2.id,
        title="Logo Designer for Eco-Friendly Campus Brand",
        description="We are starting a student-led organic cosmetics and beauty brand on campus. Need an energetic student designer to craft a modern, minimalist logo, color palette, and initial Instagram post template. Please link your previous designs in your proposal!",
        budget=350.0,
        deadline="5 Days",
        category="Graphic Design",
        university="University of Ghana",
        remote_friendly=True,
        status="open"
    )

    g2 = Gig(
        client_id=u3.id,
        title="Private Calculus II Tutor Needed",
        description="Need a patient peer tutor to prepare me for Ashesi's upcoming Calculus midterm. Must understand integrations, series, and volumes of revolution. Can meet in local study rooms or via Zoom on Tuesday evenings. GHS 120 per credit/2 hours session.",
        budget=120.0,
        deadline="mid-semester week",
        category="Tutoring & Academic",
        university="Ashesi University",
        remote_friendly=False,
        status="open"
    )

    g3 = Gig(
        client_id=u1.id,
        title="Urgent errand runner to pick package in Accra Central",
        description="Need someone travelling from Accra to KNUST (Kumasi) this Friday to help pick up a custom motherboard box from a local shop in Accra Central and bring it to campus. Perfect for someone already traveling home for the weekend.",
        budget=100.0,
        deadline="Friday",
        category="Errands & Delivery",
        university="KNUST",
        remote_friendly=False,
        status="open"
    )

    db.session.add_all([g1, g2, g3])
    db.session.commit()

    # 4. Create Seed Showcases
    s1 = ShowcasePost(
        user_id=u1.id,
        title="Custom T-Shirt Designs — Streetwear & Campus Merch",
        content="I design and print custom t-shirts for campus events, hall weeks, and personal brands. From concept sketches to final print-ready artwork, I handle everything. I've worked with 5 hall executives at KNUST for their week celebrations. DM for rates and turnaround time. Portfolio includes recent SRC election campaign designs and departmental logo concepts.",
        media_url="https://images.unsplash.com/photo-1576566588028-4147f3842f27?auto=format&fit=crop&w=600&q=80",
        media_urls="https://images.unsplash.com/photo-1576566588028-4147f3842f27?auto=format&fit=crop&w=600&q=80,https://images.unsplash.com/photo-1620799140408-edc6dcb6d633?auto=format&fit=crop&w=600&q=80,https://images.unsplash.com/photo-1583743814966-8936f5b7be1a?auto=format&fit=crop&w=600&q=80"
    )

    s2 = ShowcasePost(
        user_id=u2.id,
        title="Handmade Beaded Jewelry & Accessories",
        content="I create unique handmade beaded jewelry — necklaces, bracelets, earrings, and waist beads — using premium Ghanaian beads and materials. Each piece is custom-made to your preference. Popular for valentine's gifts, bridal shower favors, and birthday surprises. Delivery available across Legon campus and surrounding areas. Check out my gallery for inspiration!",
        media_url="https://images.unsplash.com/photo-1602173574767-37ac01994b2a?auto=format&fit=crop&w=600&q=80",
        media_urls="https://images.unsplash.com/photo-1602173574767-37ac01994b2a?auto=format&fit=crop&w=600&q=80,https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=600&q=80,https://images.unsplash.com/photo-1630019852942-f89202989a59?auto=format&fit=crop&w=600&q=80"
    )

    db.session.add_all([s1, s2])
    db.session.commit()
    print("Seed data loaded successfully!")


app = create_app()

if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host=host, port=port, debug=debug)
