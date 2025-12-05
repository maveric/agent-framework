#!/bin/bash
set -e  # Exit on error

echo "=========================================="
echo "Agent Orchestrator - Server Setup"
echo "=========================================="

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Error: Python 3 not found"; exit 1; }

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv .venv

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cat > .env << 'EOF'
# LLM Provider API Keys (add your keys here)
OPENAI_API_KEY=your-key-here
ANTHROPIC_API_KEY=your-key-here
GOOGLE_API_KEY=your-key-here

# Optional: LangSmith tracing
LANGCHAIN_TRACING_V2=false
LANGCHAIN_API_KEY=

# Frontend URL for CORS (optional)
FRONTEND_URL=http://localhost:3000
EOF
    echo "⚠️  Please edit .env and add your API keys"
fi

# Create necessary directories
echo "Creating required directories..."
mkdir -p projects/workspace
mkdir -p logs

# Setup frontend (if orchestrator-dashboard exists)
if [ -d "orchestrator-dashboard" ]; then
    echo "Setting up frontend..."
    cd orchestrator-dashboard
    
    # Check if npm is installed
    if command -v npm &> /dev/null; then
        echo "Installing npm dependencies..."
        npm install
        
        # Create .env.development if missing
        if [ ! -f .env.development ]; then
            echo "Creating frontend .env.development..."
            echo "VITE_API_URL=http://localhost:8085" > .env.development
        fi
        
        echo "Frontend setup complete!"
    else
        echo "⚠️  npm not found. Skipping frontend setup."
        echo "   Install Node.js and run: cd orchestrator-dashboard && npm install"
    fi
    
    cd ..
fi

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env and add your API keys"
echo "2. Start the backend:"
echo "   source .venv/bin/activate"
echo "   python src/server.py"
echo ""
echo "3. Start the frontend (in another terminal):"
echo "   cd orchestrator-dashboard"
echo "   npm run dev"
echo ""
echo "4. Open http://localhost:3000"
echo ""
