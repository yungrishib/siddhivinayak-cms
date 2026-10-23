import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from supabase import create_client, Client

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

app = Flask(
    __name__,
    template_folder=os.path.join(basedir, 'templates'),
    static_folder=os.path.join(basedir, 'static')
)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB upload

# Environment Credentials
db_url = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret_key_change_this')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')

# Supabase Storage Setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
STORAGE_BUCKET = "project-images"

db = SQLAlchemy(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

class Enquiry(db.Model):
    __tablename__ = 'enquiries'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(254), nullable=True)
    service = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Project(db.Model):
    __tablename__ = 'projects'
    id = db.Column(db.Integer, primary_key=True)
    sr_no = db.Column(db.String(20), nullable=False)
    name_of_work = db.Column(db.String(200), nullable=False)
    nature_of_work = db.Column(db.Text, nullable=False)
    year_or_status = db.Column(db.String(100), nullable=False)
    client_or_value = db.Column(db.String(100), nullable=False)
    image_filename = db.Column(db.String(500), nullable=True)  # Stores public Supabase URL or file path

with app.app_context():
    db.create_all()

# --- PUBLIC ROUTES ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/projects')
def projects():
    all_projects = Project.query.all()
    return render_template('projects.html', projects=all_projects)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    message = None
    error = None
    if request.method == 'POST':
        full_name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        email = (request.form.get('email') or '').strip()
        service = (request.form.get('service') or '').strip()
        user_message = (request.form.get('message') or '').strip()

        if not full_name or not phone or not service or not user_message:
            error = "Please fill in all required fields."
        else:
            try:
                new_lead = Enquiry(full_name=full_name, phone=phone, email=email if email else None, service=service, message=user_message)
                db.session.add(new_lead)
                db.session.commit()
                message = f"Thank you, {full_name}! Your enquiry has been received."
            except Exception as e:
                db.session.rollback()
                error = "Database error."
    return render_template('contact.html', message=message, error=error)

# --- ADMIN AUTHENTICATION ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_projects'))
        else:
            error = "Invalid password."
    return render_template('admin_login.html', error=error)

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

# --- ADMIN DASHBOARD ROUTES ---
@app.route('/admin/enquiries')
def view_enquiries():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    
    all_enquiries = Enquiry.query.order_by(Enquiry.created_at.desc()).all()
    return render_template('admin_enquiries.html', enquiries=all_enquiries)

@app.route('/admin/projects', methods=['GET', 'POST'])
def admin_projects():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        sr_no = request.form.get('sr_no')
        name_of_work = request.form.get('name_of_work')
        nature_of_work = request.form.get('nature_of_work')
        year_or_status = request.form.get('year_or_status')
        client_or_value = request.form.get('client_or_value')
        
        # Stream image directly to Supabase Storage
        image_url = None
        if 'project_image' in request.files:
            file = request.files['project_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"{int(datetime.utcnow().timestamp())}_{filename}"
                file_bytes = file.read()
                
                # 1. Upload bytes directly to Supabase Bucket
                supabase.storage.from_(STORAGE_BUCKET).upload(
                    path=unique_filename,
                    file=file_bytes,
                    file_options={"content-type": file.content_type}
                )
                
                # 2. Retrieve public URL
                image_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(unique_filename)

        new_project = Project(
            sr_no=sr_no,
            name_of_work=name_of_work,
            nature_of_work=nature_of_work,
            year_or_status=year_or_status,
            client_or_value=client_or_value,
            image_filename=image_url
        )
        db.session.add(new_project)
        db.session.commit()
        return redirect(url_for('admin_projects'))

    projects = Project.query.all()
    return render_template('admin_projects.html', projects=projects)

@app.route('/admin/projects/delete/<int:id>', methods=['POST'])
def delete_project(id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    
    proj = Project.query.get_or_404(id)
    if proj.image_filename:
        try:
            # Extract file name from Supabase Public URL and delete from bucket
            storage_path = proj.image_filename.split('/')[-1]
            supabase.storage.from_(STORAGE_BUCKET).remove([storage_path])
        except Exception:
            pass
            
    db.session.delete(proj)
    db.session.commit()
    return redirect(url_for('admin_projects'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)