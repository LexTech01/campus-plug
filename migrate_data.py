import sys
import os
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import create_engine, text, MetaData

def migrate(sqlite_path, pg_url):
    sqlite_engine = create_engine(f'sqlite:///{sqlite_path}')
    pg_engine = create_engine(pg_url, pool_pre_ping=True)

    metadata = MetaData()
    metadata.reflect(bind=sqlite_engine)

    table_order = [
        'users',
        'listings',
        'gigs',
        'showcase_posts',
        'showcase_likes',
        'showcase_comments',
        'messages',
        'transactions',
        'reviews',
        'proposals',
        'notifications',
        'offers',
        'cart_items',
        'admin_logs',
        'transaction_logs',
        'alembic_version',
    ]

    with pg_engine.connect() as pg_conn:
        # Clear existing data in reverse order
        for tbl in reversed(table_order):
            if tbl in metadata.tables:
                pg_conn.execute(text(f'DELETE FROM {tbl}'))
        pg_conn.commit()

        total = 0
        for table_name in table_order:
            if table_name not in metadata.tables:
                print(f"  Skipping {table_name} (table not found)")
                continue

            table = metadata.tables[table_name]
            with sqlite_engine.connect() as sqlite_conn:
                rows = sqlite_conn.execute(table.select()).fetchall()

            if not rows:
                print(f"  {table_name}: 0 rows")
                continue

            columns = [col.name for col in table.columns]
            data = []
            for row in rows:
                d = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if isinstance(val, (datetime, date)):
                        val = val.isoformat()
                    elif isinstance(val, Decimal):
                        val = float(val)
                    d[col] = val
                data.append(d)

            for d in data:
                cols = ', '.join(d.keys())
                vals = ', '.join([f':{k}' for k in d.keys()])
                pg_conn.execute(text(f'INSERT INTO {table_name} ({cols}) VALUES ({vals}) ON CONFLICT DO NOTHING'), d)

            print(f"  {table_name}: {len(data)} rows")
            total += len(data)

        # Reset sequences
        seq_map = {
            'users': 'users_id_seq',
            'listings': 'listings_id_seq',
            'gigs': 'gigs_id_seq',
            'transactions': 'transactions_id_seq',
            'messages': 'messages_id_seq',
            'reviews': 'reviews_id_seq',
            'notifications': 'notifications_id_seq',
            'offers': 'offers_id_seq',
            'cart_items': 'cart_items_id_seq',
            'proposals': 'proposals_id_seq',
            'showcase_posts': 'showcase_posts_id_seq',
            'showcase_likes': 'showcase_likes_id_seq',
            'showcase_comments': 'showcase_comments_id_seq',
        }
        for tbl, seq in seq_map.items():
            pg_conn.execute(text(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {tbl}), 1))"))

        pg_conn.commit()

    sqlite_engine.dispose()
    print(f"\nDone — {total} rows migrated")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 migrate_data.py POSTGRESQL_URL")
        print("Example: python3 migrate_data.py 'postgresql://user:pass@host:5432/campus_plug'")
        sys.exit(1)

    pg_url = sys.argv[1].replace('postgres://', 'postgresql://', 1)
    sqlite_path = os.path.join('instance', 'campus_plug.db')

    if not os.path.exists(sqlite_path):
        sqlite_path = 'campus_plug.db'
    if not os.path.exists(sqlite_path):
        print(f"SQLite database not found at {sqlite_path}")
        sys.exit(1)

    print(f"Migrating from {sqlite_path} to PostgreSQL...")
    migrate(sqlite_path, pg_url)
