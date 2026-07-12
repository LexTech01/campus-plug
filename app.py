import os
import json
import time
import uuid
import logging
import tempfile
import secrets
from pathlib import Path
from logging.handlers import RotatingFileHandler

from flask import Flask, render_template, redirect, url_for, flash, jsonify, request, send_from_directory, g
from flask_login import LoginManager, current_user, logout_user
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

@login_manager.unauthorized_handler
def unauthorized():
    flash('Please log in to access this page.', 'warning')
    return redirect(url_for('auth.login'))

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

    # Structured JSON logging with correlation IDs
    class JsonFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                'timestamp': self.formatTime(record),
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
            }
            if hasattr(record, 'correlation_id'):
                log_entry['correlation_id'] = record.correlation_id
            if record.exc_info and record.exc_info[0]:
                log_entry['exception'] = self.formatException(record.exc_info)
            return json.dumps(log_entry)

    os.makedirs('logs', exist_ok=True)
    handler = RotatingFileHandler('logs/campus_plug.log', maxBytes=10*1024*1024, backupCount=5)
    handler.setLevel(logging.INFO)
    handler.setFormatter(JsonFormatter())
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('Campus Plug starting')

    # Request-level timer for slow query detection
    @app.before_request
    def start_request_timer():
        g.correlation_id = request.headers.get('X-Correlation-ID', str(uuid.uuid4()))
        g.request_start = time.time()
        g.db_queries = 0

    @app.after_request
    def log_slow_requests(response):
        duration = time.time() - g.get('request_start', time.time())
        if duration > 1.0:
            app.logger.warning(f'SLOW REQUEST: {request.method} {request.path} took {duration:.2f}s ({g.get("db_queries", 0)} db queries)')
        return response

    # Check for suspended users on every request
    @app.before_request
    def check_suspended():
        if current_user.is_authenticated and current_user.is_suspended:
            logout_user()
            flash('Your account has been suspended by an administrator.', 'danger')
            return redirect(url_for('auth.login'))

    @app.after_request
    def log_request(response):
        if not app.debug:
            extra = {'correlation_id': g.get('correlation_id')}
            app.logger.info(f'{request.method} {request.path} -> {response.status_code}', extra=extra)
        return response

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

    # Proxy fix for correct IP detection behind reverse proxy
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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
    from blueprints.reports import reports_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(marketplace_bp)
    app.register_blueprint(freelance_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(reports_bp)

    # Custom context processors/filters for Jinja2
    @app.context_processor
    def inject_globals():
        from models import UNIVERSITIES, CATEGORIES, CONDITIONS, DELIVERY_POLICIES, MOMO_PROVIDERS, GIG_CATEGORIES
        from flask_login import current_user
        ctx = {
            'UNIVERSITIES': UNIVERSITIES,
            'CATEGORIES': CATEGORIES,
            'CONDITIONS': CONDITIONS,
            'DELIVERY_POLICIES': DELIVERY_POLICIES,
            'MOMO_PROVIDERS': MOMO_PROVIDERS,
            'GIG_CATEGORIES': GIG_CATEGORIES,
            'SUPPORT_EMAIL': 'campusplug30@gmail.com',
            'cache_buster': int(time.time()),
        }
        if current_user.is_authenticated:
            from models import Notification, Message, CartItem
            from utils import cache_get, cache_set
            uid = current_user.id
            n_count_key = f'notif_count:{uid}'
            m_count_key = f'msg_count:{uid}'
            c_count_key = f'cart_count:{uid}'
            notif_key = f'notif_recent:{uid}'
            n_count = cache_get(n_count_key)
            if n_count is None:
                n_count = Notification.query.filter_by(user_id=uid, is_read=False).count()
                cache_set(n_count_key, n_count, 10)
            ctx['unread_notifications_count'] = n_count
            m_count = cache_get(m_count_key)
            if m_count is None:
                m_count = Message.query.filter_by(recipient_id=uid, is_read=False).count()
                cache_set(m_count_key, m_count, 10)
            ctx['unread_messages_count'] = m_count
            c_count = cache_get(c_count_key)
            if c_count is None:
                c_count = CartItem.query.filter_by(buyer_id=uid).count()
                cache_set(c_count_key, c_count, 10)
            ctx['cart_count'] = c_count
            recent = cache_get(notif_key)
            if recent is None:
                recent = Notification.query.filter_by(user_id=uid).order_by(Notification.created_at.desc()).limit(5).all()
                cache_set(notif_key, [{'id': n.id, 'message': n.message, 'type': n.notification_type, 'is_read': n.is_read, 'created_at': n.created_at.isoformat(), 'link': n.link} for n in recent], 10)
            ctx['recent_notifications'] = recent
        return ctx

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
        from utils import cache_get, cache_set
        
        cached = cache_get('leaderboard')
        if cached is not None:
            return render_template('leaderboard.html', leaderboard=cached)
        
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
        
        cache_set('leaderboard', leaderboard_data, 60)
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

    # Serve static files with cache headers
    @app.route('/favicon.ico')
    def favicon():
        response = send_from_directory(app.static_folder, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
        response.headers['Cache-Control'] = 'public, max-age=86400, immutable'
        return response

    @app.route('/static/<path:filename>')
    def static_files(filename):
        response = send_from_directory(app.static_folder, filename)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        max_age = 31536000 if ext in ('css', 'js', 'png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'ico', 'woff2') else 3600
        response.headers['Cache-Control'] = f'public, max-age={max_age}, immutable'
        return response

    # Health check with detailed metrics
    @app.route('/health')
    def health():
        import platform
        from datetime import datetime as dt_module
        try:
            start = time.time()
            db.session.execute(db.text('SELECT 1'))
            db_latency = round((time.time() - start) * 1000, 1)
            r = None
            redis_latency = None
            try:
                from utils import get_redis
                r_start = time.time()
                r = get_redis()
                if r:
                    r.ping()
                    redis_latency = round((time.time() - r_start) * 1000, 1)
            except Exception:
                pass
            _lock = Path(tempfile.gettempdir()) / 'campus_plug_autorelease'
            _now = time.time()
            _last = float(_lock.read_text().strip()) if _lock.exists() else 0
            if _now - _last > 900:
                _lock.write_text(str(_now))
                try:
                    from blueprints.payments import auto_release_expired_transactions
                    auto_release_expired_transactions()
                except Exception as ae:
                    app.logger.error(f"Auto-release: {ae}")
            memory_mb = 0
            try:
                import subprocess
                result = subprocess.run(['ps', '-o', 'rss=', '-p', str(os.getpid())], capture_output=True, text=True, timeout=2)
                if result.stdout.strip():
                    memory_mb = round(int(result.stdout.strip()) / 1024, 1)
            except Exception:
                pass

            resend_status = 'not_configured'
            resend_key = os.environ.get('RESEND_API_KEY', '')
            if resend_key:
                if resend_key.startswith('re_'):
                    resend_status = 'configured'
                else:
                    resend_status = 'invalid_format'

            from mail import DEFAULT_FROM as email_from

            return jsonify({
                'status': 'healthy',
                'database': {'status': 'ok', 'latency_ms': db_latency},
                'redis': {'status': 'connected' if r else 'unavailable', 'latency_ms': redis_latency},
                'email': {
                    'provider': 'resend',
                    'api_key': resend_status,
                    'from': email_from,
                },
                'uptime': dt_module.utcnow().isoformat(),
                'python': platform.python_version(),
                'memory_mb': memory_mb,
            })
        except Exception as e:
            return jsonify({'status': 'unhealthy', 'database': {'status': 'error', 'message': str(e)}}), 500

    # Create Database and Seed if empty
    with app.app_context():
        if os.environ.get('SKIP_DB_CREATE') != '1':
            tables_created = False
            if HAS_MIGRATE and upgrade:
                try:
                    upgrade()
                    tables_created = True
                except Exception as exc:
                    app.logger.error("Migration failed, falling back to create_all: %s", exc)
                    db.create_all()
                    tables_created = True
                    try:
                        from flask_migrate import stamp
                        stamp()
                    except Exception:
                        pass
            else:
                db.create_all()
                tables_created = True

            if app.config.get('DEBUG', False) and tables_created:
                seed_data()

    return app

def seed_data():
    if User.query.first() is not None:
        return
    
    print("Database is empty. Seeding realistic Ghana Campus Plug data...")
    
    # Use dev passwords from environment if provided, otherwise generate secure random ones
    _password = os.environ.get('DEV_STUDENT_PASSWORD') or secrets.token_urlsafe(10)
    
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
    u1.set_password(_password)
    
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
    u2.set_password(_password)
    
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
    u3.set_password(_password)

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
    u4.set_password(_password)

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
    # Admin password comes from env or is generated; printed once for developer convenience
    admin_password = os.environ.get('DEV_ADMIN_PASSWORD') or secrets.token_urlsafe(12)
    u5.set_password(admin_password)

    db.session.add_all([u1, u2, u3, u4, u5])
    db.session.commit()

    # Print generated dev credentials so developer can log in locally (only when seeding in debug)
    try:
        print(f"Seeded dev credentials: STUDENT_PASSWORD=<hidden> ADMIN_PASSWORD=<hidden>")
    except Exception:
        pass

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
