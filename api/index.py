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
        'sslmode': 'require'  # Required for most cloud providers
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
        
        # Todos table
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
        
        # Create default categories if none exist
        cur.execute('SELECT COUNT(*) FROM categories')
        if cur.fetchone()['count'] == 0:
            default_categories = [
                ('Work', '#3b82f6'),
                ('Personal', '#10b981'),
                ('Shopping', '#f59e0b'),
                ('Health', '#ef4444'),
                ('Learning', '#8b5cf6')
            ]
            
            for name, color in default_categories:
                cur.execute(
                    'INSERT INTO categories (name, color) VALUES (%s, %s)', 
                    (name, color)
                )
        
        conn.commit()

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
    """Login page"""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == SECRET_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash("Wrong password! 🚫", 'error')
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login</title>
        <style>
            body { font-family: system-ui; max-width: 400px; margin: 50px auto; padding: 20px; }
            input[type="password"] { width: 100%; padding: 10px; margin: 10px 0; }
            button { width: 100%; padding: 10px; background: #3b82f6; color: white; border: none; border-radius: 5px; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <h2>🔐 Todo App Login</h2>
        <form method="post">
            <input type="password" name="password" placeholder="Enter password" required>
            <button type="submit">Login</button>
        </form>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    """Main dashboard"""
    try:
        # Initialize database if needed
        init_db()
        
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get all todos
            cur.execute('''
                SELECT t.*, c.name as category_name, c.color as category_color
                FROM todos t
                LEFT JOIN categories c ON t.category_id = c.id
                WHERE t.completed = FALSE
                ORDER BY t.priority DESC, t.created_at DESC
            ''')
            todos = cur.fetchall()
            
            # Get categories
            cur.execute('SELECT * FROM categories ORDER BY name')
            categories = cur.fetchall()
            
            # Simple HTML template for now
            html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Todo Dashboard</title>
                <style>
                    body { font-family: system-ui; max-width: 800px; margin: 0 auto; padding: 20px; }
                    .todo { background: #f3f4f6; margin: 10px 0; padding: 15px; border-radius: 8px; }
                    .high { border-left: 4px solid #dc2626; }
                    .medium { border-left: 4px solid #ef4444; }
                    .low { border-left: 4px solid #f59e0b; }
                    form { background: white; padding: 20px; border-radius: 8px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
                    input, select, textarea { width: 100%; padding: 8px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px; }
                    button { padding: 10px 20px; background: #3b82f6; color: white; border: none; border-radius: 4px; cursor: pointer; }
                    .header { display: flex; justify-content: space-between; align-items: center; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>📋 Todo Dashboard</h1>
                    <a href="/logout">Logout</a>
                </div>
                
                <form method="post" action="/add_todo">
                    <h3>Add New Todo</h3>
                    <input type="text" name="task" placeholder="Task title" required>
                    <textarea name="description" placeholder="Description (optional)"></textarea>
                    <select name="priority">
                        <option value="1">Low Priority</option>
                        <option value="2">Medium Priority</option>
                        <option value="3">High Priority</option>
                    </select>
                    <input type="date" name="due_date">
                    <select name="category_id">
                        <option value="">No Category</option>'''
            
            for category in categories:
                html += f'<option value="{category["id"]}">{category["name"]}</option>'
            
            html += '''
                    </select>
                    <button type="submit">Add Todo</button>
                </form>
                
                <h2>📝 Active Todos ({} total)</h2>
            '''.format(len(todos))
            
            for todo in todos:
                priority_class = ['', 'low', 'medium', 'high'][todo['priority']]
                html += f'''
                <div class="todo {priority_class}">
                    <h4>{todo["task"]}</h4>
                    {f"<p>{todo['description']}</p>" if todo['description'] else ""}
                    <p>Priority: {['', 'Low', 'Medium', 'High'][todo['priority']]} | 
                       Created: {todo['created_at']}
                       {f"| Category: {todo['category_name']}" if todo['category_name'] else ""}
                       {f"| Due: {todo['due_date']}" if todo['due_date'] else ""}</p>
                    <a href="/toggle_todo/{todo['id']}" style="color: green;">✅ Complete</a> | 
                    <a href="/delete_todo/{todo['id']}" style="color: red;">❌ Delete</a>
                </div>
                '''
            
            html += '''
            </body>
            </html>
            '''
            
            return html
                               
    except Exception as e:
        return f'<h2>Database Error</h2><p>{str(e)}</p><p>Check your DATABASE_URL environment variable.</p>'

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
        return redirect(url_for('dashboard'))
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO todos (task, description, priority, due_date, category_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (task, description, priority, due_date, category_id, datetime.now()))
            conn.commit()
    except Exception as e:
        return f'<h2>Error adding todo:</h2><p>{str(e)}</p><a href="/">Back to dashboard</a>'
    
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
    except Exception as e:
        return f'<h2>Error:</h2><p>{str(e)}</p><a href="/">Back to dashboard</a>'
    
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
    except Exception as e:
        return f'<h2>Error:</h2><p>{str(e)}</p><a href="/">Back to dashboard</a>'
    
    return redirect(url_for('dashboard'))

# For Vercel
def handler(event, context):
    return app(event, context)

# For local testing
if __name__ == "__main__":
    app.run(debug=True)