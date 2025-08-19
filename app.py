from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading
import time
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Your secret password - change this to whatever you want
SECRET_PASSWORD = "opensesame"

# Email configuration - now stored in database
def get_email_config():
    """Get email configuration from database"""
    conn = get_db_connection()
    config = {
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'email': '',
        'password': '',
        'enabled': False
    }
    
    try:
        settings = conn.execute('SELECT key, value FROM settings WHERE key IN (?, ?, ?)', 
                               ('email', 'email_password', 'email_enabled')).fetchall()
        
        for setting in settings:
            if setting['key'] == 'email':
                config['email'] = setting['value']
            elif setting['key'] == 'email_password':
                config['password'] = setting['value']
            elif setting['key'] == 'email_enabled':
                config['enabled'] = setting['value'] == 'true'
    except:
        pass
    finally:
        conn.close()
    
    return config

def save_email_config(email, password, enabled):
    """Save email configuration to database"""
    conn = get_db_connection()
    
    # Delete existing settings
    conn.execute('DELETE FROM settings WHERE key IN (?, ?, ?)', 
                ('email', 'email_password', 'email_enabled'))
    
    # Insert new settings
    conn.execute('INSERT INTO settings (key, value) VALUES (?, ?)', ('email', email))
    conn.execute('INSERT INTO settings (key, value) VALUES (?, ?)', ('email_password', password))
    conn.execute('INSERT INTO settings (key, value) VALUES (?, ?)', ('email_enabled', 'true' if enabled else 'false'))
    
    conn.commit()
    conn.close()

# Database setup
DATABASE = 'todos.db'

def init_db():
    """Initialize the database with all required tables"""
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    
    # Categories table
    c.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#667eea',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Todos table (enhanced)
    c.execute('''
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task TEXT NOT NULL,
            description TEXT,
            completed BOOLEAN NOT NULL DEFAULT 0,
            priority INTEGER DEFAULT 1,
            due_date DATE,
            category_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_notified DATE,
            FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
        )
    ''')
    
    # Subtasks table
    c.execute('''
        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            todo_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            completed BOOLEAN NOT NULL DEFAULT 0,
            order_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (todo_id) REFERENCES todos (id) ON DELETE CASCADE
        )
    ''')
    
    # Task notes/activity log table
    c.execute('''
        CREATE TABLE IF NOT EXISTS task_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            todo_id INTEGER NOT NULL,
            note_type TEXT DEFAULT 'note',
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (todo_id) REFERENCES todos (id) ON DELETE CASCADE
        )
    ''')
    
    # Settings table for email configuration
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Add last_notified column if it doesn't exist (for existing databases)
    try:
        c.execute('ALTER TABLE todos ADD COLUMN last_notified DATE')
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Create default categories only if categories table is empty
    c.execute('SELECT COUNT(*) FROM categories')
    if c.fetchone()[0] == 0:
        categories = [
            ('Work', '#3b82f6'),
            ('Personal', '#10b981'),
            ('Shopping', '#f59e0b'),
            ('Health', '#ef4444'),
            ('Learning', '#8b5cf6')
        ]
        
        for name, color in categories:
            c.execute('INSERT INTO categories (name, color) VALUES (?, ?)', (name, color))
    
    conn.commit()
    conn.close()

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def send_email_notification(subject, body, to_email=None):
    """Send email notification"""
    email_config = get_email_config()
    
    if not email_config['enabled'] or not email_config['email']:
        print(f"Email disabled or not configured. Would send: {subject}")
        return False
    
    try:
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
        text = msg.as_string()
        server.sendmail(email_config['email'], to_email or email_config['email'], text)
        server.quit()
        
        print(f"Email sent successfully: {subject}")
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def check_due_tasks():
    """Check for tasks due today and send notifications"""
    conn = get_db_connection()
    today = datetime.now().date().strftime('%Y-%m-%d')
    
    # Get tasks due today that haven't been notified yet
    due_tasks = conn.execute('''
        SELECT t.*, c.name as category_name, c.color as category_color
        FROM todos t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.due_date = ? 
        AND t.completed = 0 
        AND (t.last_notified IS NULL OR t.last_notified != ?)
        ORDER BY t.priority DESC, t.created_at ASC
    ''', (today, today)).fetchall()
    
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
                conn.execute('UPDATE todos SET last_notified = ? WHERE id = ?', (today, task['id']))
            conn.commit()
        
    conn.close()

def run_scheduler():
    """Run the email scheduler in background using built-in modules"""
    last_check = None
    
    while True:
        now = datetime.now()
        
        # Check at 7 AM or every 30 minutes
        should_check = (
            # First run
            last_check is None or
            # It's 7 AM and we haven't checked today
            (now.hour == 7 and now.minute < 5 and 
             (last_check is None or last_check.date() < now.date())) or
            # Every 30 minutes
            (last_check is None or (now - last_check).total_seconds() >= 1800)
        )
        
        if should_check:
            print(f"Checking for due tasks at {now}")
            check_due_tasks()
            last_check = now
        
        time.sleep(60)  # Check every minute

# Start scheduler in background thread
def start_scheduler():
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

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
    conn = get_db_connection()
    tab = request.args.get('tab', 'active')  # Default to active tab
    view = request.args.get('view', 'list')  # list or calendar
    
    if tab == 'completed':
        # Get completed todos
        todos = conn.execute('''
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.completed = 1
            ORDER BY t.updated_at DESC
        ''').fetchall()
    else:
        # Get active todos
        todos = conn.execute('''
            SELECT t.*, c.name as category_name, c.color as category_color
            FROM todos t
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE t.completed = 0
            ORDER BY 
                CASE t.priority 
                    WHEN 3 THEN 1 
                    WHEN 2 THEN 2 
                    WHEN 1 THEN 3 
                END,
                t.due_date ASC NULLS LAST,
                t.created_at DESC
        ''').fetchall()
    
    # Get subtasks for each todo
    todos_with_subtasks = []
    for todo in todos:
        subtasks = conn.execute('''
            SELECT * FROM subtasks WHERE todo_id = ? ORDER BY order_index, id
        ''', (todo['id'],)).fetchall()
        
        todo_dict = dict(todo)
        todo_dict['subtasks'] = subtasks
        todo_dict['subtask_progress'] = len([s for s in subtasks if s['completed']]) / len(subtasks) * 100 if subtasks else 0
        todos_with_subtasks.append(todo_dict)
    
    # Get categories
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    # Get stats (always for all todos)
    all_todos = conn.execute('SELECT * FROM todos').fetchall()
    total_todos = len(all_todos)
    completed_todos = len([t for t in all_todos if t['completed']])
    pending_todos = total_todos - completed_todos
    overdue_todos = len([t for t in all_todos if not t['completed'] and t['due_date'] and datetime.strptime(t['due_date'], '%Y-%m-%d').date() < datetime.now().date()])
    
    conn.close()
    
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
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO todos (task, description, priority, due_date, category_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (task, description, priority, due_date, category_id, datetime.now()))
    conn.commit()
    conn.close()
    
    flash('Todo added successfully! 🎉', 'success')
    return redirect(url_for('dashboard'))

@app.route('/toggle_todo/<int:todo_id>')
@login_required
def toggle_todo(todo_id):
    """Toggle todo completion status"""
    conn = get_db_connection()
    todo = conn.execute('SELECT * FROM todos WHERE id = ?', (todo_id,)).fetchone()
    
    if todo:
        new_status = not todo['completed']
        conn.execute('UPDATE todos SET completed = ?, updated_at = ? WHERE id = ?', 
                    (new_status, datetime.now(), todo_id))
        conn.commit()
        
        if new_status:
            flash('Todo completed! Great job! 🎯', 'success')
        else:
            flash('Todo reopened! Back to work! 💪', 'info')
    
    conn.close()
    
    # Redirect to appropriate tab
    if new_status:
        return redirect(url_for('dashboard', tab='completed'))
    else:
        return redirect(url_for('dashboard', tab='active'))

@app.route('/delete_todo/<int:todo_id>')
@login_required
def delete_todo(todo_id):
    """Delete a todo"""
    conn = get_db_connection()
    conn.execute('DELETE FROM todos WHERE id = ?', (todo_id,))
    conn.commit()
    conn.close()
    
    flash('Todo deleted! 🗑️', 'info')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/edit_todo/<int:todo_id>', methods=['GET', 'POST'])
@login_required
def edit_todo(todo_id):
    """Edit an existing todo"""
    conn = get_db_connection()
    
    if request.method == 'POST':
        task = request.form.get('task', '').strip()
        description = request.form.get('description', '').strip()
        priority = int(request.form.get('priority', 1))
        due_date = request.form.get('due_date') or None
        category_id = request.form.get('category_id') or None
        
        if not task:
            flash('Task cannot be empty!', 'error')
            return redirect(url_for('edit_todo', todo_id=todo_id))
        
        conn.execute('''
            UPDATE todos 
            SET task = ?, description = ?, priority = ?, due_date = ?, category_id = ?, updated_at = ?
            WHERE id = ?
        ''', (task, description, priority, due_date, category_id, datetime.now(), todo_id))
        
        # Add activity log
        conn.execute('''
            INSERT INTO task_notes (todo_id, note_type, content)
            VALUES (?, ?, ?)
        ''', (todo_id, 'activity', f'Task details updated'))
        
        conn.commit()
        conn.close()
        
        flash('Todo updated successfully! ✏️', 'success')
        return redirect(url_for('todo_detail', todo_id=todo_id))
    
    todo = conn.execute('SELECT * FROM todos WHERE id = ?', (todo_id,)).fetchone()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    
    if not todo:
        flash('Todo not found!', 'error')
        return redirect(url_for('dashboard'))
    
    return render_template('edit_todo.html', todo=todo, categories=categories)

@app.route('/categories')
@login_required
def categories():
    """Manage categories"""
    conn = get_db_connection()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    conn.close()
    return render_template('categories.html', categories=categories)

@app.route('/add_category', methods=['POST'])
@login_required
def add_category():
    """Add a new category"""
    name = request.form.get('name', '').strip()
    color = request.form.get('color', '#667eea')
    
    if not name:
        flash('Category name cannot be empty!', 'error')
        return redirect(url_for('categories'))
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO categories (name, color) VALUES (?, ?)', (name, color))
        conn.commit()
        flash('Category added successfully! 🏷️', 'success')
    except sqlite3.IntegrityError:
        flash('Category name already exists!', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('categories'))

@app.route('/delete_category/<int:category_id>')
@login_required
def delete_category(category_id):
    """Delete a category"""
    conn = get_db_connection()
    conn.execute('DELETE FROM categories WHERE id = ?', (category_id,))
    conn.commit()
    conn.close()
    
    flash('Category deleted! 🗑️', 'info')
    return redirect(url_for('categories'))

@app.route('/add_subtask/<int:todo_id>', methods=['POST'])
@login_required
def add_subtask(todo_id):
    """Add a subtask to a todo"""
    title = request.form.get('title', '').strip()
    
    if not title:
        flash('Subtask title cannot be empty!', 'error')
        return redirect(request.referrer or url_for('dashboard'))
    
    conn = get_db_connection()
    
    # Get the next order index
    max_order = conn.execute('SELECT MAX(order_index) as max_order FROM subtasks WHERE todo_id = ?', (todo_id,)).fetchone()
    next_order = (max_order['max_order'] or 0) + 1
    
    conn.execute('''
        INSERT INTO subtasks (todo_id, title, order_index)
        VALUES (?, ?, ?)
    ''', (todo_id, title, next_order))
    
    # Add activity log
    conn.execute('''
        INSERT INTO task_notes (todo_id, note_type, content)
        VALUES (?, ?, ?)
    ''', (todo_id, 'activity', f'Added subtask: {title}'))
    
    conn.commit()
    conn.close()
    
    flash('Subtask added! ✅', 'success')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/toggle_subtask/<int:subtask_id>')
@login_required
def toggle_subtask(subtask_id):
    """Toggle subtask completion"""
    conn = get_db_connection()
    subtask = conn.execute('SELECT * FROM subtasks WHERE id = ?', (subtask_id,)).fetchone()
    
    if subtask:
        new_status = not subtask['completed']
        conn.execute('UPDATE subtasks SET completed = ? WHERE id = ?', (new_status, subtask_id))
        
        # Add activity log
        action = 'completed' if new_status else 'reopened'
        conn.execute('''
            INSERT INTO task_notes (todo_id, note_type, content)
            VALUES (?, ?, ?)
        ''', (subtask['todo_id'], 'activity', f'Subtask "{subtask["title"]}" {action}'))
        
        conn.commit()
    
    conn.close()
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/delete_subtask/<int:subtask_id>')
@login_required
def delete_subtask(subtask_id):
    """Delete a subtask"""
    conn = get_db_connection()
    subtask = conn.execute('SELECT * FROM subtasks WHERE id = ?', (subtask_id,)).fetchone()
    
    if subtask:
        conn.execute('DELETE FROM subtasks WHERE id = ?', (subtask_id,))
        
        # Add activity log
        conn.execute('''
            INSERT INTO task_notes (todo_id, note_type, content)
            VALUES (?, ?, ?)
        ''', (subtask['todo_id'], 'activity', f'Deleted subtask: {subtask["title"]}'))
        
        conn.commit()
    
    conn.close()
    flash('Subtask deleted! 🗑️', 'info')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/add_note/<int:todo_id>', methods=['POST'])
@login_required
def add_note(todo_id):
    """Add a note to a todo"""
    content = request.form.get('content', '').strip()
    
    if not content:
        flash('Note cannot be empty!', 'error')
        return redirect(request.referrer or url_for('edit_todo', todo_id=todo_id))
    
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO task_notes (todo_id, note_type, content)
        VALUES (?, ?, ?)
    ''', (todo_id, 'note', content))
    conn.commit()
    conn.close()
    
    flash('Note added! 📝', 'success')
    return redirect(request.referrer or url_for('edit_todo', todo_id=todo_id))

@app.route('/todo_detail/<int:todo_id>')
@login_required
def todo_detail(todo_id):
    """Detailed view of a todo with notes and subtasks"""
    conn = get_db_connection()
    
    # Get todo with category info
    todo = conn.execute('''
        SELECT t.*, c.name as category_name, c.color as category_color
        FROM todos t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.id = ?
    ''', (todo_id,)).fetchone()
    
    if not todo:
        flash('Todo not found!', 'error')
        return redirect(url_for('dashboard'))
    
    # Get subtasks
    subtasks = conn.execute('''
        SELECT * FROM subtasks WHERE todo_id = ? ORDER BY order_index, id
    ''', (todo_id,)).fetchall()
    
    # Get notes and activity log
    notes = conn.execute('''
        SELECT * FROM task_notes WHERE todo_id = ? ORDER BY created_at DESC
    ''', (todo_id,)).fetchall()
    
    # Get categories for editing
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    conn.close()
    
    return render_template('todo_detail.html', 
                         todo=todo, 
                         subtasks=subtasks,
                         notes=notes,
                         categories=categories)

@app.route('/api/todo_stats')
@login_required
def todo_stats():
    """API endpoint for todo statistics"""
    conn = get_db_connection()
    
    # Get todos by category
    category_stats = conn.execute('''
        SELECT c.name, c.color, COUNT(t.id) as count
        FROM categories c
        LEFT JOIN todos t ON c.id = t.category_id AND t.completed = 0
        GROUP BY c.id, c.name, c.color
        HAVING count > 0
        ORDER BY count DESC
    ''').fetchall()
    
    # Get todos by priority
    priority_stats = conn.execute('''
        SELECT priority, COUNT(*) as count
        FROM todos
        WHERE completed = 0
        GROUP BY priority
        ORDER BY priority DESC
    ''').fetchall()
    
    conn.close()
    
    return jsonify({
        'categories': [dict(row) for row in category_stats],
        'priorities': [dict(row) for row in priority_stats]
    })

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """Email settings page"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        enabled = bool(request.form.get('enabled'))
        
        if email and password:
            save_email_config(email, password, enabled)
            flash('Email settings saved! 📧', 'success')
        else:
            flash('Please provide both email and password!', 'error')
        
        return redirect(url_for('settings'))
    
    email_config = get_email_config()
    return render_template('settings.html', email_config=email_config)

@app.route('/test_email')
@login_required
def test_email():
    """Test email functionality"""
    config = get_email_config()
    print(f"DEBUG: Email config - Email: {config['email']}, Password: {'*' * len(config['password']) if config['password'] else 'EMPTY'}, Enabled: {config['enabled']}")
    
    if send_email_notification(
        "📧 Test Email from Todo App", 
        "<h2>Email notifications are working!</h2><p>This is a test email from your Todo app.</p>"
    ):
        flash('Test email sent successfully! 📧', 'success')
    else:
        flash('Failed to send test email. Check your settings.', 'error')
    
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

if __name__ == '__main__':
    try:
        print("Starting todo app...")
        init_db()
        print("Database initialized successfully")
        
        # Check for due tasks on startup
        check_due_tasks()
        print("Due tasks check completed")
        
        # Start email scheduler
        start_scheduler()
        print("Email scheduler started")
        
        print("Starting Flask app on port 5000...")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        print(f"ERROR starting app: {e}")
        import traceback
        traceback.print_exc()