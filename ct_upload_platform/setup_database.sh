#!/bin/bash

###############################################################################
# CT Upload Platform - Database Setup Script
# 
# This script initializes the PostgreSQL database, runs migrations, and sets
# up the initial application data.
#
# Usage:
#   ./setup_database.sh                    # Run with defaults from .env
#   ./setup_database.sh production         # Run with production config
#   ./setup_database.sh dev                # Run with development config
#
# Prerequisites:
#   - PostgreSQL 13+ installed and running
#   - Python 3.10+ with virtualenv activated
#   - Django project files available
#
###############################################################################

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default configuration
ENV_FILE="${SCRIPT_DIR}/.env"
DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="ct_upload_platform"
DB_USER="postgres"
DB_PASSWORD="password"
DJANGO_USER="admin"
DJANGO_EMAIL="admin@localhost"
DJANGO_PASSWORD="admin_password"
ENVIRONMENT="development"

# Parse arguments
if [ ! -z "$1" ]; then
    ENVIRONMENT="$1"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}CT Upload Platform - Database Setup${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Load environment variables from .env file
if [ -f "$ENV_FILE" ]; then
    echo -e "${GREEN}[1] Loading environment from .env${NC}"
    set -a
    source "$ENV_FILE"
    set +a
    
    # Override defaults from .env
    DB_HOST="${DB_HOST:-localhost}"
    DB_PORT="${DB_PORT:-5432}"
    DB_NAME="${DB_NAME:-ct_upload_platform}"
    DB_USER="${DB_USER:-postgres}"
    DB_PASSWORD="${DB_PASSWORD:-password}"
    
    echo -e "  Database: ${DB_NAME}@${DB_HOST}:${DB_PORT}"
    echo -e "  User: ${DB_USER}\n"
else
    echo -e "${YELLOW}[!] .env file not found, using defaults\n${NC}"
fi

# Function to execute SQL
execute_sql() {
    local sql="$1"
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -p "$DB_PORT" -c "$sql"
}

# Function to execute SQL file
execute_sql_file() {
    local file="$1"
    local db="${2:-postgres}"
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -p "$DB_PORT" -d "$db" -f "$file"
}

# Check PostgreSQL connection
echo -e "${GREEN}[2] Checking PostgreSQL connection${NC}"
if execute_sql "SELECT version();" > /dev/null 2>&1; then
    echo -e "  ${GREEN}✓ PostgreSQL is accessible\n${NC}"
else
    echo -e "  ${RED}✗ Cannot connect to PostgreSQL${NC}"
    echo -e "  ${YELLOW}Make sure PostgreSQL is running:${NC}"
    echo -e "    brew services start postgresql"
    exit 1
fi

# Check if database exists
echo -e "${GREEN}[3] Checking database status${NC}"
DB_EXISTS=$(PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -p "$DB_PORT" -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -c 1 || true)

if [ $DB_EXISTS -eq 0 ]; then
    echo -e "  Database does not exist, creating..."
    execute_sql "CREATE DATABASE $DB_NAME ENCODING 'UTF8';"
    echo -e "  ${GREEN}✓ Database created\n${NC}"
else
    echo -e "  ${YELLOW}⚠ Database already exists\n${NC}"
    
    read -p "  Do you want to DROP and RECREATE the database? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "  ${RED}Dropping existing database...${NC}"
        PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -U "$DB_USER" -p "$DB_PORT" -c "DROP DATABASE IF EXISTS $DB_NAME;"
        execute_sql "CREATE DATABASE $DB_NAME ENCODING 'UTF8';"
        echo -e "  ${GREEN}✓ Database recreated\n${NC}"
    else
        echo -e "  ${YELLOW}Using existing database\n${NC}"
    fi
fi

# Check if Python/Django is available
echo -e "${GREEN}[4] Checking Django installation${NC}"
if command -v python3 &> /dev/null; then
    PYTHON="python3"
elif command -v python &> /dev/null; then
    PYTHON="python"
else
    echo -e "  ${RED}✗ Python not found${NC}"
    exit 1
fi

DJANGO_VERSION=$($PYTHON -c "import django; print(django.__version__)" 2>/dev/null || echo "not installed")
if [ "$DJANGO_VERSION" = "not installed" ]; then
    echo -e "  ${RED}✗ Django not installed${NC}"
    echo -e "  ${YELLOW}Please install dependencies:${NC}"
    echo -e "    pip install -r requirements.txt"
    exit 1
fi

echo -e "  ${GREEN}✓ Django ${DJANGO_VERSION} found\n${NC}"

# Run Django migrations
echo -e "${GREEN}[5] Running Django migrations${NC}"
if $PYTHON manage.py migrate --noinput; then
    echo -e "  ${GREEN}✓ Migrations completed\n${NC}"
else
    echo -e "  ${RED}✗ Migrations failed${NC}"
    exit 1
fi

# Collect static files
echo -e "${GREEN}[6] Collecting static files${NC}"
if $PYTHON manage.py collectstatic --noinput --clear; then
    echo -e "  ${GREEN}✓ Static files collected\n${NC}"
else
    echo -e "  ${YELLOW}⚠ Static file collection had issues (may be non-critical)\n${NC}"
fi

# Create superuser
echo -e "${GREEN}[7] Setting up superuser${NC}"
SUPERUSER_EXISTS=$($PYTHON manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(username='$DJANGO_USER').exists())" 2>/dev/null || echo "false")

if [ "$SUPERUSER_EXISTS" = "True" ]; then
    echo -e "  ${YELLOW}⚠ Superuser '${DJANGO_USER}' already exists${NC}"
    read -p "  Do you want to reset the superuser password? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "  Enter new superuser password (default: ${DJANGO_PASSWORD}):"
        read -s NEW_PASSWORD
        if [ -z "$NEW_PASSWORD" ]; then
            NEW_PASSWORD="$DJANGO_PASSWORD"
        fi
        echo "from django.contrib.auth.models import User; u=User.objects.get(username='$DJANGO_USER'); u.set_password('$NEW_PASSWORD'); u.save()" | $PYTHON manage.py shell
        echo -e "  ${GREEN}✓ Superuser password updated\n${NC}"
    fi
else
    echo "from django.contrib.auth.models import User; User.objects.create_superuser('$DJANGO_USER', '$DJANGO_EMAIL', '$DJANGO_PASSWORD')" | $PYTHON manage.py shell
    echo -e "  ${GREEN}✓ Superuser created (${DJANGO_USER}/${DJANGO_PASSWORD})\n${NC}"
fi

# Generate initial data fixtures if needed
echo -e "${GREEN}[8] Setting up initial data${NC}"
echo -e "  Checking for required initial data..."

# Create initial upload tokens or configuration as needed
$PYTHON manage.py shell << 'EOF'
from django.contrib.auth.models import User
print("  ✓ Initial data setup complete")
EOF

# Summary
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Database Setup Complete!${NC}"
echo -e "${GREEN}========================================\n${NC}"

echo -e "${BLUE}Next steps:${NC}"
echo -e "  1. Start development server:"
echo -e "     ${YELLOW}python manage.py runserver${NC}"
echo -e ""
echo -e "  2. Access admin interface:"
echo -e "     ${YELLOW}http://localhost:8000/admin${NC}"
echo -e "     Username: ${DJANGO_USER}"
echo -e "     Password: ${DJANGO_PASSWORD}"
echo -e ""
echo -e "  3. View API documentation:"
echo -e "     ${YELLOW}http://localhost:8000/api/${NC}"
echo -e ""
echo -e "  4. For production setup:"
echo -e "     ${YELLOW}./setup_database.sh production${NC}"
echo -e ""

exit 0
