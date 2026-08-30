#!/usr/bin/env python3
"""
CT Upload Platform - Database Setup Script

This script initializes the PostgreSQL database, runs migrations, and sets up
the initial application data.

Usage:
    python3 setup_database.py                 # Interactive setup
    python3 setup_database.py --auto          # Auto setup with defaults
    python3 setup_database.py --skip-data     # Skip initial data setup
    python3 setup_database.py --reset         # Drop and recreate database

Prerequisites:
    - PostgreSQL 13+ installed and running
    - Python 3.10+ with Django installed
    - .env file with database configuration
"""

import os
import sys
import secrets
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# Colors
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    OKYELLOW = '\033[93m'
    OKRED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    """Print colored header"""
    print(f"\n{Colors.OKBLUE}{'='*50}{Colors.ENDC}")
    print(f"{Colors.OKBLUE}{text}{Colors.ENDC}")
    print(f"{Colors.OKBLUE}{'='*50}{Colors.ENDC}\n")

def print_step(step_num, text):
    """Print step"""
    print(f"{Colors.OKGREEN}[{step_num}] {text}{Colors.ENDC}")

def print_success(text):
    """Print success message"""
    print(f"  {Colors.OKGREEN}✓ {text}{Colors.ENDC}")

def print_warning(text):
    """Print warning message"""
    print(f"  {Colors.OKYELLOW}⚠ {text}{Colors.ENDC}")

def print_error(text):
    """Print error message"""
    print(f"  {Colors.OKRED}✗ {text}{Colors.ENDC}")

def run_command(cmd, cwd=None, check=True):
    """Run shell command and return result"""
    try:
        result = subprocess.run(
            cmd,
            shell=isinstance(cmd, str),
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False
        )
        if check and result.returncode != 0:
            print_error(f"Command failed: {cmd}")
            if result.stderr:
                print(f"  {result.stderr}")
            return False
        return True
    except Exception as e:
        print_error(f"Failed to run command: {e}")
        return False

def load_env_file(env_path):
    """Load environment variables from .env file"""
    env_vars = {}
    try:
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
        return env_vars
    except Exception as e:
        print_error(f"Failed to load .env file: {e}")
        return {}

def check_postgres_connection(host, port, user, password):
    """Check PostgreSQL connection"""
    cmd = f'PGPASSWORD="{password}" psql -h {host} -p {port} -U {user} -c "SELECT version();"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0

def check_database_exists(host, port, user, password, db_name):
    """Check if database exists"""
    cmd = f'PGPASSWORD="{password}" psql -h {host} -p {port} -U {user} -tc "SELECT 1 FROM pg_database WHERE datname=\'{db_name}\'"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0 and '1' in result.stdout

def execute_sql(host, port, user, password, db_name, sql):
    """Execute SQL command"""
    cmd = f'PGPASSWORD="{password}" psql -h {host} -p {port} -U {user} -d {db_name} -c "{sql}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0, result.stdout, result.stderr

def main():
    """Main setup function"""
    
    parser = argparse.ArgumentParser(description='CT Upload Platform Database Setup')
    parser.add_argument('--auto', action='store_true', help='Run with default values')
    parser.add_argument('--skip-data', action='store_true', help='Skip initial data setup')
    parser.add_argument('--reset', action='store_true', help='Drop and recreate database')
    args = parser.parse_args()
    
    # Get script directory
    script_dir = Path(__file__).parent
    env_file = script_dir / '.env'
    
    print_header("CT Upload Platform - Database Setup")
    
    # Step 1: Load environment
    print_step(1, "Loading environment configuration")
    
    env_vars = {}
    if env_file.exists():
        env_vars = load_env_file(env_file)
        print_success(f"Loaded from {env_file}")
    else:
        print_warning(f".env file not found at {env_file}")
    
    # Database configuration
    db_host = env_vars.get('DB_HOST', 'localhost')
    db_port = env_vars.get('DB_PORT', '5432')
    db_name = env_vars.get('DB_NAME', 'ct_upload_platform')
    db_user = env_vars.get('DB_USER', 'postgres')
    db_password = env_vars.get('DB_PASSWORD', 'password')
    
    print(f"  Database: {db_name}@{db_host}:{db_port}")
    print(f"  User: {db_user}\n")
    
    # Step 2: Check PostgreSQL connection
    print_step(2, "Checking PostgreSQL connection")
    
    if not check_postgres_connection(db_host, db_port, db_user, db_password):
        print_error("Cannot connect to PostgreSQL")
        print("  Make sure PostgreSQL is running:")
        print("    brew services start postgresql  # macOS")
        print("    systemctl start postgresql       # Linux")
        sys.exit(1)
    
    print_success("PostgreSQL is accessible\n")
    
    # Step 3: Check database status
    print_step(3, "Checking database status")
    
    db_exists = check_database_exists(db_host, db_port, db_user, db_password, db_name)
    
    if db_exists:
        print_warning(f"Database '{db_name}' already exists")
        
        if args.reset:
            print("  Dropping existing database...")
            cmd = f'PGPASSWORD="{db_password}" psql -h {db_host} -p {db_port} -U {db_user} -c "DROP DATABASE IF EXISTS {db_name};"'
            subprocess.run(cmd, shell=True, capture_output=True)
            print_success("Database dropped")
            db_exists = False
        elif not args.auto:
            response = input("  Drop and recreate? (y/n): ").lower()
            if response == 'y':
                cmd = f'PGPASSWORD="{db_password}" psql -h {db_host} -p {db_port} -U {db_user} -c "DROP DATABASE IF EXISTS {db_name};"'
                subprocess.run(cmd, shell=True, capture_output=True)
                print_success("Database dropped")
                db_exists = False
    
    if not db_exists:
        print("  Creating database...")
        cmd = f'PGPASSWORD="{db_password}" psql -h {db_host} -p {db_port} -U {db_user} -c "CREATE DATABASE {db_name} ENCODING \'UTF8\';"'
        result = subprocess.run(cmd, shell=True, capture_output=True)
        if result.returncode == 0:
            print_success("Database created\n")
        else:
            print_error("Failed to create database")
            sys.exit(1)
    else:
        print_success("Using existing database\n")
    
    # Step 4: Check Django
    print_step(4, "Checking Django installation")
    
    try:
        import django
        print_success(f"Django {django.__version__} found\n")
    except ImportError:
        print_error("Django not installed")
        print("  Install dependencies: pip install -r requirements.txt")
        sys.exit(1)
    
    # Change to script directory for Django commands
    os.chdir(script_dir)
    
    # Step 5: Run migrations
    print_step(5, "Running Django migrations")
    
    if run_command(f"{sys.executable} manage.py migrate --noinput"):
        print_success("Migrations completed\n")
    else:
        print_error("Migrations failed")
        sys.exit(1)
    
    # Step 6: Collect static files
    print_step(6, "Collecting static files")
    
    if run_command(f"{sys.executable} manage.py collectstatic --noinput --clear", check=False):
        print_success("Static files collected\n")
    else:
        print_warning("Static file collection had issues (may be non-critical)\n")
    
    # Step 7: Create superuser
    print_step(7, "Setting up superuser")
    
    django_user = "admin"
    django_email = "admin@localhost"
    # Generated per run rather than a fixed default — a hardcoded default
    # superuser password here is exactly the pattern that led to this
    # project's real Orthanc/DB/SECRET_KEY credentials being left at their
    # insecure defaults in a live deployment. Printed once below so the
    # operator can capture it.
    django_password = secrets.token_urlsafe(12)
    
    # Check if user exists
    check_cmd = f'{sys.executable} manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(username=\'{django_user}\').exists())"'
    result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True, cwd=script_dir)
    user_exists = 'True' in result.stdout
    
    if user_exists:
        print_warning(f"Superuser '{django_user}' already exists")
        
        if not args.auto:
            response = input("  Reset superuser password? (y/n): ").lower()
            if response == 'y':
                new_password = input("  Enter new password (or press Enter for default): ").strip()
                if not new_password:
                    new_password = django_password
                
                sql = f"from django.contrib.auth.models import User; u=User.objects.get(username='{django_user}'); u.set_password('{new_password}'); u.save()"
                cmd = f'{sys.executable} manage.py shell -c "{sql}"'
                subprocess.run(cmd, shell=True, cwd=script_dir)
                print_success(f"Superuser password updated\n")
    else:
        sql = f"from django.contrib.auth.models import User; User.objects.create_superuser('{django_user}', '{django_email}', '{django_password}')"
        cmd = f'{sys.executable} manage.py shell -c "{sql}"'
        result = subprocess.run(cmd, shell=True, capture_output=True, cwd=script_dir)
        
        if result.returncode == 0:
            print_success(f"Superuser created ({django_user}/{django_password})\n")
        else:
            print_error("Failed to create superuser")
    
    # Step 8: Summary
    print_header("Database Setup Complete!")
    
    print(f"{Colors.OKBLUE}Next steps:{Colors.ENDC}")
    print(f"  1. Start development server:")
    print(f"     {Colors.OKYELLOW}python manage.py runserver{Colors.ENDC}")
    print()
    print(f"  2. Access admin interface:")
    print(f"     {Colors.OKYELLOW}http://localhost:8000/admin{Colors.ENDC}")
    print(f"     Username: {django_user}")
    print(f"     Password: {django_password}")
    print()
    print(f"  3. View API documentation:")
    print(f"     {Colors.OKYELLOW}http://localhost:8000/api/{Colors.ENDC}")
    print()
    print(f"  4. Check database schema:")
    print(f"     {Colors.OKYELLOW}database_schema.sql{Colors.ENDC}")
    print()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
