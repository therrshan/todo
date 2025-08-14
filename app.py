from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Your secret password - change this to whatever you want
SECRET_PASSWORD = "opensesame"

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
            FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL
        )
    ''')
    
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
    
    # Get todos with category info
    todos = conn.execute('''
        SELECT t.*, c.name as category_name, c.color as category_color
        FROM todos t
        LEFT JOIN categories c ON t.category_id = c.id
        ORDER BY 
            CASE t.priority 
                WHEN 3 THEN 1 
                WHEN 2 THEN 2 
                WHEN 1 THEN 3 
            END,
            t.due_date ASC NULLS LAST,
            t.created_at DESC
    ''').fetchall()
    
    # Get categories
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    # Get stats
    total_todos = len(todos)
    completed_todos = len([t for t in todos if t['completed']])
    pending_todos = total_todos - completed_todos
    overdue_todos = len([t for t in todos if not t['completed'] and t['due_date'] and datetime.strptime(t['due_date'], '%Y-%m-%d').date() < datetime.now().date()])
    
    conn.close()
    
    # Get today's date for overdue comparison
    today = datetime.now().date().strftime('%Y-%m-%d')
    
    return render_template('dashboard.html', 
                         todos=todos, 
                         categories=categories,
                         today=today,
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
    return redirect(url_for('dashboard'))

@app.route('/delete_todo/<int:todo_id>')
@login_required
def delete_todo(todo_id):
    """Delete a todo"""
    conn = get_db_connection()
    conn.execute('DELETE FROM todos WHERE id = ?', (todo_id,))
    conn.commit()
    conn.close()
    
    flash('Todo deleted! 🗑️', 'info')
    return redirect(url_for('dashboard'))

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
        conn.commit()
        conn.close()
        
        flash('Todo updated successfully! ✏️', 'success')
        return redirect(url_for('dashboard'))
    
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

@app.route('/clear_completed')
@login_required
def clear_completed():
    """Clear all completed todos"""
    conn = get_db_connection()
    result = conn.execute('DELETE FROM todos WHERE completed = 1')
    count = result.rowcount
    conn.commit()
    conn.close()
    
    flash(f'Cleared {count} completed todos! 🧹', 'info')
    return redirect(url_for('dashboard'))

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

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)