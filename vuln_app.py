from flask import Flask, request, render_template_string, redirect, url_for, session, make_response
import sqlite3
import os
import pickle
import subprocess
from hashlib import md5

app = Flask(__name__)
app.secret_key = 'insecure_secret_key_123'  # Hardcoded secret key

# Vulnerable HTML template with multiple issues
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Super Vulnerable App</title>
</head>
<body>
    <h1>Welcome to Super Vulnerable App!</h1>
    
    {% if message %}
    <div class="message">{{ message|safe }}</div>
    {% endif %}
    
    {% if user %}
    <p>Logged in as: {{ user.username }} (ID: {{ user.id }})</p>
    <a href="/logout">Logout</a>
    {% endif %}
    
    <h2>Login</h2>
    <form method="POST" action="/login">
        <input type="text" name="username" placeholder="Username">
        <input type="password" name="password" placeholder="Password">
        <button type="submit">Login</button>
    </form>
    
    <h2>Search</h2>
    <form method="GET" action="/search">
        <input type="text" name="query" placeholder="Search...">
        <button type="submit">Search</button>
    </form>
    
    {% if results %}
    <h3>Search Results:</h3>
    <ul>
        {% for result in results %}
        <li>{{ result }}</li>
        {% endfor %}
    </ul>
    {% endif %}
    
    <h2>File Upload</h2>
    <form method="POST" action="/upload" enctype="multipart/form-data">
        <input type="file" name="file">
        <button type="submit">Upload</button>
    </form>
    
    <h2>Profile</h2>
    <a href="/profile?user_id=1">View Profile</a>
    
    <h2>Reset Password</h2>
    <form method="POST" action="/reset_password">
        <input type="text" name="username" placeholder="Username">
        <button type="submit">Reset Password</button>
    </form>
    
    <h2>Admin Panel</h2>
    <a href="/admin">Admin Panel</a>
    
    <h2>Remember Me</h2>
    <form method="POST" action="/remember_me">
        <input type="checkbox" name="remember" value="true">
        <button type="submit">Set Preference</button>
    </form>
    
    <!-- Debug info exposed -->
    <div style="position: fixed; bottom: 0; background: #eee; padding: 10px;">
        <h3>Debug Info (Insecure!)</h3>
        <p>Session: {{ session }}</p>
        <p>Cookies: {{ request.cookies }}</p>
    </div>
</body>
</html>
"""

# Initialize a vulnerable SQLite database
def init_db():
    if not os.path.exists('vulnerable.db'):
        conn = sqlite3.connect('vulnerable.db')
        cursor = conn.cursor()
        cursor.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, is_admin INTEGER)')
        cursor.execute("INSERT INTO users (username, password, is_admin) VALUES ('admin', 'password123', 1)")
        cursor.execute("INSERT INTO users (username, password, is_admin) VALUES ('user', 'letmein', 0)")
        cursor.execute("CREATE TABLE passwords (user_id INTEGER, reset_token TEXT)")
        conn.commit()
        conn.close()

init_db()

@app.route('/')
def home():
    # Expose session and cookie data in template (information disclosure)
    return render_template_string(HTML_TEMPLATE, session=session, user=session.get('user'))

# SQL Injection vulnerability
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    
    # Weak password hashing
    password_hash = md5(password.encode()).hexdigest()
    
    conn = sqlite3.connect('vulnerable.db')
    cursor = conn.cursor()
    
    # This is intentionally vulnerable to SQL injection
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    cursor.execute(query)
    user_data = cursor.fetchone()
    conn.close()
    
    if user_data:
        # Serialize user object (insecure)
        user = {'id': user_data[0], 'username': user_data[1], 'is_admin': user_data[3]}
        session['user'] = user
        return render_template_string(HTML_TEMPLATE, message=f"Welcome {user['username']}! You are logged in.", user=user)
    else:
        return render_template_string(HTML_TEMPLATE, message="Login failed!")

# XSS vulnerability
@app.route('/search')
def search():
    query = request.args.get('query', '')
    results = []
    
    if query:
        # Simulate search results (vulnerable to reflected XSS)
        results = [f"Result for {query}", f"Another result for {query}"]
        # Also vulnerable to OS command injection
        if query.startswith('!'):
            try:
                cmd_output = subprocess.check_output(query[1:], shell=True, stderr=subprocess.STDOUT)
                results.append(f"Command output: {cmd_output.decode()}")
            except Exception as e:
                results.append(f"Command failed: {str(e)}")
    
    return render_template_string(HTML_TEMPLATE, results=results)

# Unrestricted file upload vulnerability
@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return render_template_string(HTML_TEMPLATE, message="No file uploaded!")
    
    file = request.files['file']
    if file.filename == '':
        return render_template_string(HTML_TEMPLATE, message="No file selected!")
    
    # Save the file without any validation (vulnerable)
    upload_dir = 'uploads'
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
    
    filepath = os.path.join(upload_dir, file.filename)
    file.save(filepath)
    
    # Path traversal vulnerability
    if request.args.get('custom_path'):
        custom_path = request.args.get('custom_path')
        file.save(os.path.join(upload_dir, custom_path, file.filename))
    
    return render_template_string(HTML_TEMPLATE, message=f"File uploaded successfully to {filepath}!")

# Insecure Direct Object Reference (IDOR)
@app.route('/profile')
def profile():
    user_id = request.args.get('user_id')
    conn = sqlite3.connect('vulnerable.db')
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
    user_data = cursor.fetchone()
    conn.close()
    
    if user_data:
        return render_template_string(HTML_TEMPLATE, message=f"Profile for {user_data[1]} (Admin: {bool(user_data[3])})")
    else:
        return render_template_string(HTML_TEMPLATE, message="User not found!")

# Broken Authentication - Password Reset Vulnerability
@app.route('/reset_password', methods=['POST'])
def reset_password():
    username = request.form['username']
    
    # Generate predictable reset token
    reset_token = md5(username.encode()).hexdigest()
    
    conn = sqlite3.connect('vulnerable.db')
    cursor = conn.cursor()
    cursor.execute(f"SELECT id FROM users WHERE username = '{username}'")
    user = cursor.fetchone()
    
    if user:
        # Store token in database (no expiration)
        cursor.execute(f"INSERT INTO passwords VALUES ({user[0]}, '{reset_token}')")
        conn.commit()
        conn.close()
        
        # Insecure: Display reset token directly to user
        return render_template_string(HTML_TEMPLATE, message=f"Reset token: {reset_token}")
    else:
        conn.close()
        return render_template_string(HTML_TEMPLATE, message="User not found!")

# Insecure Deserialization
@app.route('/remember_me', methods=['POST'])
def remember_me():
    remember = request.form.get('remember') == 'true'
    
    if remember and 'user' in session:
        # Insecure serialization of user object
        serialized_user = pickle.dumps(session['user'])
        resp = make_response(render_template_string(HTML_TEMPLATE, message="Remember me set!"))
        resp.set_cookie('remember_me', serialized_user.hex())
        return resp
    
    return render_template_string(HTML_TEMPLATE, message="Remember me not set")

# Broken Access Control
@app.route('/admin')
def admin_panel():
    # No proper authorization check
    if 'user' in session and session['user'].get('is_admin'):
        return render_template_string(HTML_TEMPLATE, message="Welcome to Admin Panel!")
    else:
        # Still shows admin panel but with limited functionality (insecure)
        return render_template_string(HTML_TEMPLATE, message="Regular user admin panel view")

# Logout with insecure session handling
@app.route('/logout')
def logout():
    # Doesn't properly invalidate session
    session.pop('user', None)
    return redirect(url_for('home'))

if __name__ == '__main__':
    # Running with debug mode enabled (security risk)
    app.run(debug=True, host='0.0.0.0')