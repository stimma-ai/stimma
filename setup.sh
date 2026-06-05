#!/bin/bash

echo "=== Stimma Setup ==="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10+"
    exit 1
fi
echo "✅ Python 3 found: $(python3 --version)"

# Check Node
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install Node.js 18+"
    exit 1
fi
echo "✅ Node.js found: $(node --version)"

# Check npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm not found. Please install npm"
    exit 1
fi
echo "✅ npm found: $(npm --version)"

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️  FFmpeg not found. Video processing will not work."
    echo "   Install with: brew install ffmpeg"
else
    echo "✅ FFmpeg found: $(ffmpeg -version | head -n1)"
fi

echo ""
echo "Setting up backend..."

# Create virtual environment
cd backend
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies (this may take a few minutes)..."
pip install --upgrade pip
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Failed to install Python dependencies"
    exit 1
fi

echo "✅ Backend dependencies installed"

cd ..

echo ""
echo "Setting up frontend..."

# Install frontend dependencies
cd frontend
echo "Installing Node.js dependencies..."
npm install

if [ $? -ne 0 ]; then
    echo "❌ Failed to install Node.js dependencies"
    exit 1
fi

echo "✅ Frontend dependencies installed"

cd ..

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Edit config.yaml to set your media paths"
echo "2. Run './start.sh' to start the application"
echo "3. Open http://localhost:5173 in your browser"
echo ""
echo "Note: On first run, the CLIP model (~3.5GB) will be downloaded automatically."
echo "      This may take several minutes depending on your internet connection."
echo ""
