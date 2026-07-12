from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from models import db, Report
from utils import sanitize_plain_text

reports_bp = Blueprint('reports', __name__)

REPORT_REASONS = ['spam', 'fake', 'fraud', 'inappropriate', 'duplicate', 'other']

@reports_bp.route('/report', methods=['POST'])
@login_required
def submit_report():
    target_type = request.form.get('target_type')
    target_id = request.form.get('target_id', type=int)
    reason = request.form.get('reason')
    details = sanitize_plain_text(request.form.get('details', '').strip())

    if target_type not in ('listing', 'gig', 'user'):
        flash('Invalid report target.', 'danger')
        return redirect(request.referrer or url_for('index'))

    if reason not in REPORT_REASONS:
        flash('Please select a valid reason for your report.', 'danger')
        return redirect(request.referrer or url_for('index'))

    if target_type == 'user' and target_id == current_user.id:
        flash('You cannot report yourself.', 'warning')
        return redirect(request.referrer or url_for('index'))

    existing = Report.query.filter_by(
        reporter_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        status='pending'
    ).first()
    if existing:
        flash('You have already reported this. An admin will review it shortly.', 'warning')
        return redirect(request.referrer or url_for('index'))

    report = Report(
        reporter_id=current_user.id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        details=details
    )
    db.session.add(report)
    db.session.commit()

    flash('Thank you. Your report has been submitted for review.', 'success')
    return redirect(request.referrer or url_for('index'))
