from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import os
from datetime import datetime, timedelta
from functools import wraps
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse
from contextlib import contextmanager
import threading
import time

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(16))

# Your secret password
SECRET_PASSWORD = os.environ.get('SECRET_PASSWORD', 'opensesame')

def get_database_url():
    """Get database URL from environment"""
    return os.environ.get('DATABASE_URL', os.environ.get('POSTGRES_URL'))

def parse_database_url(url):
    """Parse database URL into connection parameters"""
    if not url:
        raise ValueError("No database URL found")
    
    # Handle both postgres:// and postgresql:// schemes
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    
    parsed = urlparse(url)
    return {
        'host': parsed.hostname,
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/'),
        'user': parsed.username,
        'password': parsed.password,
        'sslmode': 'require'
    }

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = None
    try:
        db_url = get_database_url()
        if not db_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        db_params = parse_database_url(db_url)
        conn = psycopg2.connect(**db_params, cursor_factory=psycopg2.extras.RealDictCursor)
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize the database with all required tables"""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Categories table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                color VARCHAR(7) DEFAULT '#667eea',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Todos table (enhanced)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS todos (
                id SERIAL PRIMARY KEY,
                task TEXT NOT NULL,
                description TEXT,
                completed BOOLEAN NOT NULL DEFAULT FALSE,
                priority INTEGER DEFAULT 1,
                due_date DATE,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_notified DATE
            )
        ''')
        
        # Subtasks table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS subtasks (
                id SERIAL PRIMARY KEY,
                todo_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT FALSE,
                order_index INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Task notes/activity log table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS task_notes (
                id SERIAL PRIMARY KEY,
                todo_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
                note_type VARCHAR(50) DEFAULT 'note',
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Settings table for email configuration
        cur.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(255) PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Create default categories only if categories table is empty
        cur.execute('SELECT COUNT(*) FROM categories')
        if cur.fetchone()['count'] == 0:
            categories = [
                ('Work', '#3b82f6'),
                ('Personal', '#10b981'),
                ('Shopping', '#f59e0b'),
                ('Health', '#ef4444'),
                ('Learning', '#8b5cf6')
            ]
            
            for name, color in categories:
                cur.execute('INSERT INTO categories (name, color) VALUES (%s, %s)', (name, color))
        
        conn.commit()

# Email configuration functions
def get_email_config():
    """Get email configuration from database"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT key, value FROM settings WHERE key IN ('email', 'email_password', 'email_enabled')"
            )
            settings = cur.fetchall()
            
            config = {
                'smtp_server': 'smtp.gmail.com',
                'smtp_port': 587,
                'email': '',
                'password': '',
                'enabled': False
            }
            
            for setting in settings:
                if setting['key'] == 'email':
                    config['email'] = setting['value']
                elif setting['key'] == 'email_password':
                    config['password'] = setting['value']
                elif setting['key'] == 'email_enabled':
                    config['enabled'] = setting['value'] == 'true'
            
            return config
    except Exception as e:
        print(f"Error getting email config: {e}")
        return {
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'email': '',
            'password': '',
            'enabled': False
        }

def save_email_config(email, password, enabled):
    """Save email configuration to database"""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        # Delete existing settings
        cur.execute(
            "DELETE FROM settings WHERE key IN ('email', 'email_password', 'email_enabled')"
        )
        
        # Insert new settings
        cur.execute("INSERT INTO settings (key, value) VALUES ('email', %s)", (email,))
        cur.execute("INSERT INTO settings (key, value) VALUES ('email_password', %s)", (password,))
        cur.execute("INSERT INTO settings (key, value) VALUES ('email_enabled', %s)", ('true' if enabled else 'false',))
        
        conn.commit()

def send_email_notification(subject, body, to_email=None):
    """Send email notification with enhanced debugging"""
    email_config = get_email_config()
    
    print(f"DEBUG: Email config check:")
    print(f"  - Email: {email_config['email']}")
    print(f"  - Password set: {'Yes' if email_config['password'] else 'No'}")
    print(f"  - Enabled: {email_config['enabled']}")
    
    if not email_config['enabled']:
        print("EMAIL: Notifications disabled in settings")
        return False
        
    if not email_config['email']:
        print("EMAIL: No email address configured")
        return False
        
    if not email_config['password']:
        print("EMAIL: No email password configured")
        return False
    
    try:
        print(f"EMAIL: Attempting to send email...")
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = email_config['email']
        msg['To'] = to_email or email_config['email']
        msg['Subject'] = subject
        
        # Add body to email
        msg.attach(MIMEText(body, 'html'))
        
        # Gmail SMTP configuration
        server = smtplib.SMTP(email_config['smtp_server'], email_config['smtp_port'])
        server.starttls()
        server.login(email_config['email'], email_config['password'])
        server.sendmail(email_config['email'], to_email or email_config['email'], msg.as_string())
        server.quit()
        
        print(f"EMAIL: Successfully sent: {subject}")
        return True
        
    except Exception as e:
        print(f"EMAIL: Error sending notification - {e}")
        return False

def check_due_tasks():
    """Check for tasks due today and send notifications"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            today = datetime.now().date().strftime('%Y-%m-%d')
            
            # Get tasks due today that haven't been notified yet
            cur.execute('''
                SELECT t.*, c.name as category_name, c.color as category_color
                FROM todos t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.due_date = %s 
                AND t.completed = FALSE 
                AND (t.last_notified IS NULL OR t.last_notified != %s)
                ORDER BY t.priority DESC, t.created_at ASC
            ''', (today, today))
            
            due_tasks = cur.fetchall()
            
            if due_tasks:
                # Create email content
                task_count = len(due_tasks)
                subject = f"📋 {task_count} Task{'s' if task_count > 1 else ''} Due Today - {datetime.now().strftime('%B %d, %Y')}"
                
                # Create HTML email body
                html_body = f"""
                <html>
                <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
                    <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                        <h1 style="margin: 0; font-size: 24px;">📋 Tasks Due Today</h1>
                        <p style="margin: 10px 0 0 0; opacity: 0.9;">{datetime.now().strftime('%A, %B %d, %Y')}</p>
                    </div>
                    <div style="background: #f8f9fa; padding: 20px; border-radius: 0 0 10px 10px;">
                        <p style="margin-top: 0;">You have <strong>{task_count}</strong> task{'s' if task_count > 1 else ''} due today:</p>
                """
                
                for task in due_tasks:
                    priority_colors = {1: '#f59e0b', 2: '#ef4444', 3: '#dc2626'}
                    priority_labels = {1: 'Low', 2: 'Medium', 3: 'High'}
                    
                    html_body += f"""
                        <div style="background: white; margin: 10px 0; padding: 15px; border-radius: 8px; border-left: 4px solid {priority_colors.get(task['priority'], '#667eea')};">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                                <h3 style="margin: 0; color: #333;">{task['task']}</h3>
                                <span style="background: {priority_colors.get(task['priority'], '#667eea')}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: bold;">
                                    {priority_labels.get(task['priority'], 'Medium')}
                                </span>
                            </div>
                    """
                    
                    if task['description']:
                        html_body += f"<p style='margin: 8px 0; color: #666; font-size: 14px;'>{task['description']}</p>"
                    
                    if task['category_name']:
                        html_body += f"<span style='background: {task['category_color']}; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px;'>{task['category_name']}</span>"
                    
                    html_body += "</div>"
                
                html_body += """
                        <p style="margin-top: 20px; color: #666; font-size: 14px;">
                            💡 <strong>Tip:</strong> Open your Todo Dashboard to manage these tasks!
                        </p>
                    </div>
                </body>
                </html>
                """
                
                # Send email
                if send_email_notification(subject, html_body):
                    # Mark tasks as notified
                    for task in due_tasks:
                        cur.execute('UPDATE todos SET last_notified = %s WHERE id = %s', (today, task['id']))
                    conn.commit()
                    
    except Exception as e:
        print(f"Error checking due tasks: {e}")

def login_required(f):
    """Decorator to check if user is logged in"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page with quirky messages"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == SECRET_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            quirky_messages = [
                "Get the fuck off my laptop! 🖕",
                "Nice try, but NOPE! 😤",
                "Access denied, you sneaky bastard! 🚫",
                "Wrong password, smartass! 🙄",
                "Back off, this ain't for you! 👋",
                "Unauthorized access detected! Calling the cyber police! 🚨",
                "Password incorrect. Please try being me instead. 🤷‍♂️",
                "Error 401: You're not worthy! ⚡",
                "Begone, password peasant! 🏰",
                "That's not the magic word, muggle! 🧙‍♂️"
            ]
            import random
            flash(random.choice(quirky_messages), 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    flash('See you later! 👋', 'info')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    """Main dashboard with todo overview"""
    try:
        # Initialize database if needed
        init_db()
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            tab = request.args.get('tab', 'active')  # Default to active tab
            view = request.args.get('view', 'list')  # list or calendar
            
            if tab == 'completed':
                # Get completed todos
                cur.execute('''
                    SELECT t.*, c.name as category_name, c.color as category_color
                    FROM todos t
                    LEFT JOIN categories c ON t.category_id = c.id
                    WHERE t.completed = TRUE
                    ORDER BY t.updated_at DESC
                ''')
            else:
                # Get active todos
                cur.execute('''
                    SELECT t.*, c.name as category_name, c.color as category_color
                    FROM todos t
                    LEFT JOIN categories c ON t.category_id = c.id
                    WHERE t.completed = FALSE
                    ORDER BY 
                        CASE t.priority 
                            WHEN 3 THEN 1 
                            WHEN 2 THEN 2 
                            WHEN 1 THEN 3 
                        END,
                        t.due_date ASC NULLS LAST,
                        t.created_at DESC
                ''')
            
            todos = cur.fetchall()
            
            # Get subtasks for each todo
            todos_with_subtasks = []
            for todo in todos:
                cur.execute('''
                    SELECT * FROM subtasks WHERE todo_id = %s ORDER BY order_index, id
                ''', (todo['id'],))
                subtasks = cur.fetchall()
                
                todo_dict = dict(todo)
                todo_dict['subtasks'] = subtasks
                todo_dict['subtask_progress'] = len([s for s in subtasks if s['completed']]) / len(subtasks) * 100 if subtasks else 0
                todos_with_subtasks.append(todo_dict)
            
            # Get categories
            cur.execute('SELECT * FROM categories ORDER BY name')
            categories = cur.fetchall()
            
            # Get stats (always for all todos)
            cur.execute('SELECT * FROM todos')
            all_todos = cur.fetchall()
            total_todos = len(all_todos)
            completed_todos = len([t for t in all_todos if t['completed']])
            pending_todos = total_todos - completed_todos
            overdue_todos = len([t for t in all_todos if not t['completed'] and t['due_date'] and t['due_date'] < datetime.now().date()])
            
            # Get today's date for overdue comparison
            today = datetime.now().date().strftime('%Y-%m-%d')
            
            if view == 'calendar':
                return render_template('calendar.html',
                                     todos=todos_with_subtasks,
                                     categories=categories,
                                     today=today,
                                     current_tab=tab,
                                     current_view=view,
                                     stats={
                                         'total': total_todos,
                                         'completed': completed_todos,
                                         'pending': pending_todos,
                                         'overdue': overdue_todos
                                     })
            
            return render_template('dashboard.html', 
                                 todos=todos_with_subtasks, 
                                 categories=categories,
                                 today=today,
                                 current_tab=tab,
                                 current_view=view,
                                 stats={
                                     'total': total_todos,
                                     'completed': completed_todos,
                                     'pending': pending_todos,
                                     'overdue': overdue_todos
                                 })
                                 
    except Exception as e:
        return f'<h2>Database Error</h2><p>{str(e)}</p><p>Check your DATABASE_URL environment variable.</p><a href="/login">Login</a>'

@app.route('/add_todo', methods=['POST'])
@login_required
def add_todo():
    """Add a new todo"""
    task = request.form.get('task', '').strip()
    description = request.form.get('description', '').strip()
    priority = int(request.form.get('priority', 1))
    due_date = request.form.get('due_date') or None
    category_id = request.form.get('category_id') or None
    
    if not task:
        flash('Task cannot be empty!', 'error')
        return redirect(url_for('dashboard'))
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO todos (task, description, priority, due_date, category_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (task, description, priority, due_date, category_id, datetime.now()))
            conn.commit()
        
        flash('Todo added successfully! 🎉', 'success')
    except Exception as e:
        flash(f'Error adding todo: {e}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/toggle_todo/<int:todo_id>')
@login_required
def toggle_todo(todo_id):
    """Toggle todo completion status"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM todos WHERE id = %s', (todo_id,))
            todo = cur.fetchone()
            
            if todo:
                new_status = not todo['completed']
                cur.execute('UPDATE todos SET completed = %s, updated_at = %s WHERE id = %s', 
                           (new_status, datetime.now(), todo_id))
                conn.commit()
                
                if new_status:
                    flash('Todo completed! Great job! 🎯', 'success')
                    return redirect(url_for('dashboard', tab='completed'))
                else:
                    flash('Todo reopened! Back to work! 💪', 'info')
                    return redirect(url_for('dashboard', tab='active'))
    except Exception as e:
        flash(f'Error updating todo: {e}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/delete_todo/<int:todo_id>')
@login_required
def delete_todo(todo_id):
    """Delete a todo"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM todos WHERE id = %s', (todo_id,))
            conn.commit()
        
        flash('Todo deleted! 🗑️', 'info')
    except Exception as e:
        flash(f'Error deleting todo: {e}', 'error')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/edit_todo/<int:todo_id>', methods=['GET', 'POST'])
@login_required
def edit_todo(todo_id):
    """Edit an existing todo"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            if request.method == 'POST':
                task = request.form.get('task', '').strip()
                description = request.form.get('description', '').strip()
                priority = int(request.form.get('priority', 1))
                due_date = request.form.get('due_date') or None
                category_id = request.form.get('category_id') or None
                
                if not task:
                    flash('Task cannot be empty!', 'error')
                    return redirect(url_for('edit_todo', todo_id=todo_id))
                
                cur.execute('''
                    UPDATE todos 
                    SET task = %s, description = %s, priority = %s, due_date = %s, category_id = %s, updated_at = %s
                    WHERE id = %s
                ''', (task, description, priority, due_date, category_id, datetime.now(), todo_id))
                
                # Add activity log
                cur.execute('''
                    INSERT INTO task_notes (todo_id, note_type, content)
                    VALUES (%s, %s, %s)
                ''', (todo_id, 'activity', f'Task details updated'))
                
                conn.commit()
                
                flash('Todo updated successfully! ✏️', 'success')
                return redirect(url_for('todo_detail', todo_id=todo_id))
            
            cur.execute('SELECT * FROM todos WHERE id = %s', (todo_id,))
            todo = cur.fetchone()
            cur.execute('SELECT * FROM categories ORDER BY name')
            categories = cur.fetchall()
            
            if not todo:
                flash('Todo not found!', 'error')
                return redirect(url_for('dashboard'))
            
            return render_template('edit_todo.html', todo=todo, categories=categories)
            
    except Exception as e:
        flash(f'Error editing todo: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/categories')
@login_required
def categories():
    """Manage categories"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM categories ORDER BY name')
            categories = cur.fetchall()
        return render_template('categories.html', categories=categories)
    except Exception as e:
        flash(f'Error loading categories: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/add_category', methods=['POST'])
@login_required
def add_category():
    """Add a new category"""
    name = request.form.get('name', '').strip()
    color = request.form.get('color', '#667eea')
    
    if not name:
        flash('Category name cannot be empty!', 'error')
        return redirect(url_for('categories'))
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('INSERT INTO categories (name, color) VALUES (%s, %s)', (name, color))
            conn.commit()
        flash('Category added successfully! 🏷️', 'success')
    except psycopg2.IntegrityError:
        flash('Category name already exists!', 'error')
    except Exception as e:
        flash(f'Error adding category: {e}', 'error')
    
    return redirect(url_for('categories'))

@app.route('/delete_category/<int:category_id>')
@login_required
def delete_category(category_id):
    """Delete a category"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('DELETE FROM categories WHERE id = %s', (category_id,))
            conn.commit()
        flash('Category deleted! 🗑️', 'info')
    except Exception as e:
        flash(f'Error deleting category: {e}', 'error')
    
    return redirect(url_for('categories'))

@app.route('/add_subtask/<int:todo_id>', methods=['POST'])
@login_required
def add_subtask(todo_id):
    """Add a subtask to a todo"""
    title = request.form.get('title', '').strip()
    
    if not title:
        flash('Subtask title cannot be empty!', 'error')
        return redirect(request.referrer or url_for('dashboard'))
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get the next order index
            cur.execute('SELECT MAX(order_index) as max_order FROM subtasks WHERE todo_id = %s', (todo_id,))
            max_order = cur.fetchone()
            next_order = (max_order['max_order'] or 0) + 1
            
            cur.execute('''
                INSERT INTO subtasks (todo_id, title, order_index)
                VALUES (%s, %s, %s)
            ''', (todo_id, title, next_order))
            
            # Add activity log
            cur.execute('''
                INSERT INTO task_notes (todo_id, note_type, content)
                VALUES (%s, %s, %s)
            ''', (todo_id, 'activity', f'Added subtask: {title}'))
            
            conn.commit()
        
        flash('Subtask added! ✅', 'success')
    except Exception as e:
        flash(f'Error adding subtask: {e}', 'error')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/toggle_subtask/<int:subtask_id>')
@login_required
def toggle_subtask(subtask_id):
    """Toggle subtask completion"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM subtasks WHERE id = %s', (subtask_id,))
            subtask = cur.fetchone()
            
            if subtask:
                new_status = not subtask['completed']
                cur.execute('UPDATE subtasks SET completed = %s WHERE id = %s', (new_status, subtask_id))
                
                # Add activity log
                action = 'completed' if new_status else 'reopened'
                cur.execute('''
                    INSERT INTO task_notes (todo_id, note_type, content)
                    VALUES (%s, %s, %s)
                ''', (subtask['todo_id'], 'activity', f'Subtask "{subtask["title"]}" {action}'))
                
                conn.commit()
    except Exception as e:
        flash(f'Error updating subtask: {e}', 'error')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete_subtask/<int:subtask_id>')
@login_required
def delete_subtask(subtask_id):
    """Delete a subtask"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('SELECT * FROM subtasks WHERE id = %s', (subtask_id,))
            subtask = cur.fetchone()
            
            if subtask:
                cur.execute('DELETE FROM subtasks WHERE id = %s', (subtask_id,))
                
                # Add activity log
                cur.execute('''
                    INSERT INTO task_notes (todo_id, note_type, content)
                    VALUES (%s, %s, %s)
                ''', (subtask['todo_id'], 'activity', f'Deleted subtask: {subtask["title"]}'))
                
                conn.commit()
        
        flash('Subtask deleted! 🗑️', 'info')
    except Exception as e:
        flash(f'Error deleting subtask: {e}', 'error')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/add_note/<int:todo_id>', methods=['POST'])
@login_required
def add_note(todo_id):
    """Add a note to a todo"""
    content = request.form.get('content', '').strip()
    
    if not content:
        flash('Note cannot be empty!', 'error')
        return redirect(request.referrer or url_for('edit_todo', todo_id=todo_id))
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO task_notes (todo_id, note_type, content)
                VALUES (%s, %s, %s)
            ''', (todo_id, 'note', content))
            conn.commit()
        
        flash('Note added! 📝', 'success')
    except Exception as e:
        flash(f'Error adding note: {e}', 'error')
    
    return redirect(request.referrer or url_for('edit_todo', todo_id=todo_id))

@app.route('/todo_detail/<int:todo_id>')
@login_required
def todo_detail(todo_id):
    """Detailed view of a todo with notes and subtasks"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get todo with category info
            cur.execute('''
                SELECT t.*, c.name as category_name, c.color as category_color
                FROM todos t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.id = %s
            ''', (todo_id,))
            todo = cur.fetchone()
            
            if not todo:
                flash('Todo not found!', 'error')
                return redirect(url_for('dashboard'))
            
            # Get subtasks
            cur.execute('''
                SELECT * FROM subtasks WHERE todo_id = %s ORDER BY order_index, id
            ''', (todo_id,))
            subtasks = cur.fetchall()
            
            # Get notes and activity log
            cur.execute('''
                SELECT * FROM task_notes WHERE todo_id = %s ORDER BY created_at DESC
            ''', (todo_id,))
            notes = cur.fetchall()
            
            # Get categories for editing
            cur.execute('SELECT * FROM categories ORDER BY name')
            categories = cur.fetchall()
            
            return render_template('todo_detail.html', 
                                 todo=todo, 
                                 subtasks=subtasks,
                                 notes=notes,
                                 categories=categories)
                                 
    except Exception as e:
        flash(f'Error loading todo details: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/api/todo_stats')
@login_required
def todo_stats():
    """API endpoint for todo statistics"""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get todos by category
            cur.execute('''
                SELECT c.name, c.color, COUNT(t.id) as count
                FROM categories c
                LEFT JOIN todos t ON c.id = t.category_id AND t.completed = FALSE
                GROUP BY c.id, c.name, c.color
                HAVING COUNT(t.id) > 0
                ORDER BY count DESC
            ''')
            category_stats = cur.fetchall()
            
            # Get todos by priority
            cur.execute('''
                SELECT priority, COUNT(*) as count
                FROM todos
                WHERE completed = FALSE
                GROUP BY priority
                ORDER BY priority DESC
            ''')
            priority_stats = cur.fetchall()
            
            return jsonify({
                'categories': [dict(row) for row in category_stats],
                'priorities': [dict(row) for row in priority_stats]
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Email settings page"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        enabled = bool(request.form.get('enabled'))
        
        if email and password:
            try:
                save_email_config(email, password, enabled)
                flash('Email settings saved! 📧', 'success')
            except Exception as e:
                flash(f'Error saving settings: {e}', 'error')
        else:
            flash('Please provide both email and password!', 'error')
        
        return redirect(url_for('settings'))
    
    email_config = get_email_config()
    return render_template('settings.html', email_config=email_config)

@app.route('/test_email')
@login_required
def test_email():
    """Test email functionality with detailed feedback"""
    print("=" * 50)
    print("STARTING EMAIL TEST")
    print("=" * 50)
    
    if send_email_notification(
        "🔧 Test Email from Todo App", 
        "<h2>Email notifications are working!</h2><p>This is a test email from your Todo app on Vercel.</p>"
    ):
        flash('Test email sent successfully! 📧', 'success')
    else:
        flash('Failed to send test email. Check the Vercel logs for detailed error info.', 'error')
    
    print("=" * 50)
    print("EMAIL TEST COMPLETED")
    print("=" * 50)
    
    return redirect(url_for('settings'))

@app.route('/debug_email')
@login_required
def debug_email():
    """Debug email settings"""
    config = get_email_config()
    return f"""
    <h3>Email Configuration Debug:</h3>
    <p><strong>Email:</strong> {config['email'] or 'NOT SET'}</p>
    <p><strong>Password:</strong> {'*' * len(config['password']) if config['password'] else 'NOT SET'}</p>
    <p><strong>Enabled:</strong> {config['enabled']}</p>
    <p><strong>SMTP Server:</strong> {config['smtp_server']}</p>
    <p><strong>SMTP Port:</strong> {config['smtp_port']}</p>
    <br>
    <a href="/settings">Back to Settings</a>
    """

# Initialize database on startup
try:
    print("Initializing database...")
    init_db()
    print("Database initialized successfully!")
    
    # Check for due tasks on startup (only in production)
    if not os.environ.get('FLASK_ENV') == 'development':
        check_due_tasks()
        print("Due tasks check completed")
        
except Exception as e:
    print(f"Error during startup: {e}")

# For local testing
if __name__ == "__main__":
    app.run(debug=True)