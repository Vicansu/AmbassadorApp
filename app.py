import os
import uuid 
import random
from flask import Flask, render_template, redirect, url_for, flash, request, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, TextAreaField, FileField, IntegerField
from wtforms.validators import DataRequired
from werkzeug.utils import secure_filename
from datetime import datetime

# --- CONFIGURATION ---
app = Flask(__name__)
# IMPORTANT: Use environment variables for production security (Render handles these)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_strong_fallback_secret_key')
# Use a simple SQLite DB for demonstration. Render typically uses PostgreSQL in production.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///quiz_platform.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static/uploads')
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'png', 'jpg', 'jpeg', 'mp3'}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- DATABASE MODELS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20)) # 'teacher' or 'student'
    attempts = db.relationship('QuizAttempt', backref='student', lazy='dynamic')
    diagnostics = db.relationship('DiagnosticAttempt', backref='student', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    text = db.Column(db.Text, nullable=False)
    # difficulty can be 'diagnostic', 'easy', 'intermediate', 'hard'
    difficulty = db.Column(db.String(15)) 
    subject = db.Column(db.String(50))
    grade = db.Column(db.String(10))
    topic = db.Column(db.String(50))
    media_path = db.Column(db.String(255), nullable=True) 
    is_passage = db.Column(db.Boolean, default=False)
    passage_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=True) 
    linked_questions = db.relationship('Question', 
                                       backref=db.backref('main_passage', remote_side=[id]), 
                                       lazy='dynamic', 
                                       foreign_keys=[passage_id])

class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    subject = db.Column(db.String(50))
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    is_practice = db.Column(db.Boolean, default=False)
    score = db.Column(db.Float, default=0.0)

# New model for enforcing the diagnostic step
class DiagnosticAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Stores the recommended difficulty level based on diagnostic result
    recommended_level = db.Column(db.String(15), default='intermediate') 

# --- FORMS ---

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Log In')

class QuestionForm(FlaskForm):
    subject = StringField('Subject', validators=[DataRequired()])
    grade = StringField('Grade/Class (e.g., 10th)', validators=[DataRequired()])
    topic = StringField('Topic (e.g., Photosynthesis)', validators=[DataRequired()])
    difficulty = SelectField('Difficulty', choices=[('diagnostic', 'Diagnostic'), ('easy', 'Easy'), ('intermediate', 'Intermediate'), ('hard', 'Hard')], validators=[DataRequired()])
    is_passage = SelectField('Question Type', choices=[('False', 'Single Question'), ('True', 'Main Passage/Context')], coerce=lambda x: x == 'True')
    passage_id = SelectField('Attach to Passage (Optional)', choices=[], coerce=int, nullable=True)
    text = TextAreaField('Question Text / Passage Content', validators=[DataRequired()])
    media_file = FileField('Upload Media (PDF/MP3/Image)')
    submit = SubmitField('Save Question')


# --- AUTHENTICATION & UTILITIES ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.before_first_request
def create_db_and_admin():
    db.create_all()
    if not User.query.filter_by(username='teacher1').first():
        t = User(username='teacher1', role='teacher')
        t.set_password('password')
        db.session.add(t)
    if not User.query.filter_by(username='student1').first():
        s = User(username='student1', role='student')
        s.set_password('password')
        db.session.add(s)
    
    # Pre-load Diagnostic Questions if none exist
    if not Question.query.filter_by(difficulty='diagnostic').first():
        for i in range(5):
            q = Question(teacher_id=1, text=f'Diagnostic Question {i+1}: What is the capital of France?', 
                         difficulty='diagnostic', subject='General', grade='All', topic='Basic Knowledge')
            db.session.add(q)
            
    db.session.commit()

# --- ROUTES ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if current_user.is_authenticated:
        return redirect(url_for(f'{current_user.role}_dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash(f'Welcome, {user.username}!', 'success')
            return redirect(url_for(f'{user.role}_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    
    return render_template('index.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# --- TEACHER ROUTES ---

@app.route('/teacher_dashboard')
@login_required
def teacher_dashboard():
    if current_user.role != 'teacher':
        flash('Access denied.', 'danger'); return redirect(url_for('student_dashboard'))
    
    all_questions = Question.query.filter_by(teacher_id=current_user.id).order_by(Question.id.desc()).all()
    
    # Mock data for live reporting chart
    live_report_data = {
        'subjects': ['Math', 'Science', 'History'],
        'scores': [85, 72, 91]
    }
    
    return render_template('teacher_dashboard.html', 
                           total_questions=len(all_questions), 
                           all_questions=all_questions,
                           live_report_data=live_report_data)

@app.route('/create_question', methods=['GET', 'POST'])
@login_required
def create_question():
    if current_user.role != 'teacher':
        flash('Access denied.', 'danger'); return redirect(url_for('student_dashboard'))

    form = QuestionForm()
    # Populate passage selection
    form.passage_id.choices = [(None, 'None (Standalone Question)')] + \
                              [(p.id, f"ID {p.id}: {p.subject} ({p.topic})") 
                               for p in Question.query.filter_by(teacher_id=current_user.id, is_passage=True).all()]

    if form.validate_on_submit():
        media_path = None
        if form.media_file.data and form.media_file.data.filename and allowed_file(form.media_file.data.filename):
            file = form.media_file.data
            filename = secure_filename(file.filename)
            unique_filename = str(uuid.uuid4()) + "_" + filename
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(save_path)
            media_path = url_for('static', filename=f'uploads/{unique_filename}')

        passage_id = form.passage_id.data if not form.is_passage.data and form.passage_id.data else None

        new_question = Question(
            teacher_id=current_user.id,
            text=form.text.data,
            difficulty=form.difficulty.data,
            subject=form.subject.data,
            grade=form.grade.data,
            topic=form.topic.data,
            media_path=media_path,
            is_passage=form.is_passage.data,
            passage_id=passage_id
        )
        db.session.add(new_question)
        db.session.commit()
        flash('Question saved successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))

    return render_template('create_question.html', form=form)

# Report Generation (Mocking the file output)
@app.route('/report/<report_type>/<target>')
@login_required
def generate_report(report_type, target):
    if current_user.role != 'teacher':
        flash('Access denied.', 'danger'); return redirect(url_for('student_dashboard'))
    
    report_content = f"""
    Quiz Report for {current_user.username} - {report_type.capitalize()}
    Target: {target}
    Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    
    --- MOCK CLASS/TOPIC DATA ---
    Student IDs: 
    - 12345 (Math Score: 85%, Topic: Algebra - 90%)
    - 54321 (Math Score: 62%, Topic: Algebra - 55%)
    
    Summary: 
    Average Score for {target}: 73.5%
    """
    
    temp_file_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{target}_{report_type}_report.txt')
    with open(temp_file_path, 'w') as f:
        f.write(report_content)
        
    flash(f'Generating {report_type} report for {target}.', 'info')
    
    return send_file(temp_file_path, as_attachment=True, 
                     download_name=f"{target}_{report_type}_Report.txt")

# --- STUDENT ROUTES ---

@app.route('/student_dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        flash('Access denied.', 'danger'); return redirect(url_for('teacher_dashboard'))

    diagnostic_completed = DiagnosticAttempt.query.filter_by(student_id=current_user.id).first()

    # Mock available quizzes based on subjects/grades
    available_quizzes = [
        {'id': 1, 'subject': 'Physics', 'grade': '10th', 'difficulty': 'Intermediate', 'duration': 45},
        {'id': 2, 'subject': 'Math', 'grade': '10th', 'difficulty': 'Hard', 'duration': 60},
    ]

    return render_template('student_dashboard.html', 
                           diagnostic_completed=diagnostic_completed,
                           available_quizzes=available_quizzes)

@app.route('/diagnostic_quiz', methods=['GET', 'POST'])
@login_required
def diagnostic_quiz():
    if current_user.role != 'student':
        flash('Access denied.', 'danger'); return redirect(url_for('teacher_dashboard'))
        
    if DiagnosticAttempt.query.filter_by(student_id=current_user.id).first():
        flash('You have already completed the diagnostic test.', 'info')
        return redirect(url_for('student_dashboard'))
    
    questions = Question.query.filter_by(difficulty='diagnostic').all()
    
    if request.method == 'POST':
        # MOCK SCORING LOGIC
        score = sum(1 for q_id, ans in request.form.items() if q_id.startswith('answer_'))
        
        # Simple recommendation logic based on mock score
        if score >= 4:
            recommended_level = 'hard'
        elif score >= 2:
            recommended_level = 'intermediate'
        else:
            recommended_level = 'easy'
            
        new_attempt = DiagnosticAttempt(
            student_id=current_user.id,
            recommended_level=recommended_level
        )
        db.session.add(new_attempt)
        db.session.commit()
        
        flash(f'Diagnostic completed! Your recommended level is {recommended_level}.', 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('diagnostic_quiz.html', 
                           questions=questions, 
                           time_limit_seconds=300) # 5 minutes for diagnostic

@app.route('/start_quiz/<int:quiz_id>')
@login_required
def start_quiz(quiz_id):
    if current_user.role != 'student':
        flash('Access denied.', 'danger'); return redirect(url_for('teacher_dashboard'))

    diagnostic_check = DiagnosticAttempt.query.filter_by(student_id=current_user.id).first()
    if not diagnostic_check:
        flash('Please complete the diagnostic quiz first!', 'warning')
        return redirect(url_for('diagnostic_quiz'))
    
    # MOCK QUIZ GENERATION based on recommended difficulty
    recommended_level = diagnostic_check.recommended_level
    
    # Filter by recommended level, subject, and grade
    quiz_questions = Question.query.filter(
        Question.difficulty.in_([recommended_level, 'intermediate']), # Mix it up
        Question.subject=='Physics', # Mock subject
        Question.grade=='10th'     # Mock grade
    ).limit(10).all()
    
    if not quiz_questions:
        flash("No main quiz questions found for your level. Try again later.", 'warning')
        return redirect(url_for('student_dashboard'))
    
    # Mock QuizAttempt tracking
    attempt = QuizAttempt(student_id=current_user.id, subject='Physics')
    db.session.add(attempt)
    db.session.commit()

    return render_template('quiz_attempt.html', 
                           attempt_id=attempt.id, 
                           questions=quiz_questions, 
                           time_limit_seconds=3600) # 60 minutes for main quiz

@app.route('/submit_quiz/<int:attempt_id>', methods=['POST'])
@login_required
def submit_quiz(attempt_id):
    is_practice = request.form.get('practice_mode') == 'true'
    
    attempt = QuizAttempt.query.get_or_404(attempt_id)
    attempt.end_time = datetime.utcnow()
    attempt.is_practice = is_practice
    
    # MOCK SCORING
    attempt.score = random.randint(50, 95) if not is_practice else 0.0
    db.session.commit()
    
    flash(f'Quiz submitted! Score: {attempt.score}% (Practice Mode: {attempt.is_practice})', 'success')
    return redirect(url_for('student_dashboard'))

# The following lines are necessary for gunicorn/Render deployment
if __name__ == '__main__':
    app.run(debug=True)
