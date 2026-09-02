# U-CONNECT Deployment Guide - Render

## 📋 Pre-Deployment Checklist

✅ **Files ready for deployment:**
- `requirements.txt` — Python dependencies
- `render.yaml` — Infrastructure configuration
- `.gitignore` — Excluded files
- `backend/app.py` — Updated for production
- `frontend/` — Mobile-responsive PWA ready
- `database/` — SQLite database

---

## 🚀 Step 1: Push to GitHub

1. **Initialize git** (if not already done):
   ```bash
   cd "c:\Users\Thabo\OneDrive\Desktop\Internship\app project\app"
   git init
   git add .
   git commit -m "Initial commit: U-CONNECT PWA ready for deployment"
   ```

2. **Create GitHub repo:**
   - Go to [github.com/new](https://github.com/new)
   - Create a new repository named `uconnect-app`
   - Copy the commands to push your code:
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/uconnect-app.git
   git branch -M main
   git push -u origin main
   ```

---

## 🌐 Step 2: Deploy on Render

1. **Sign up (free):**
   - Go to [render.com](https://render.com)
   - Click "Sign up"
   - Sign in with GitHub (easiest)

2. **Create new Web Service:**
   - Click "New +" → "Web Service"
   - Connect your GitHub account
   - Select `uconnect-app` repository
   - Click "Connect"

3. **Configure deployment:**

   | Setting | Value |
   |---------|-------|
   | **Name** | `uconnect-app` |
   | **Environment** | `Python 3` |
   | **Build Command** | `pip install -r requirements.txt` |
   | **Start Command** | `gunicorn backend.app:app` |
   | **Plan** | Free (0.50 USD/month) |

4. **Environment Variables:**
   - Click "Environment"
   - Add these variables:
     ```
     FLASK_ENV = production
     PYTHON_VERSION = 3.11.0
     ```

5. **Deploy:**
   - Click "Create Web Service"
   - Wait 2-5 minutes for deployment
   - You'll get a URL like: `https://uconnect-app.onrender.com`

---

## ✅ Step 3: Test Deployment

Once deployed, test these endpoints:

```bash
# Health check
curl https://uconnect-app.onrender.com/health

# Get announcements
curl https://uconnect-app.onrender.com/api/announcements

# Get students
curl https://uconnect-app.onrender.com/api/students

# Create a student
curl -X POST https://uconnect-app.onrender.com/api/student \
  -H "Content-Type: application/json" \
  -d '{"full_name":"John Doe","email":"john@example.com"}'
```

---

## 🔗 Step 4: Update Frontend Configuration

Update your `frontend/app.js` to point to the new backend:

```javascript
// At the top of app.js, add:
const API_BASE = 'https://uconnect-app.onrender.com';

// Replace all fetch calls from:
fetch('/api/...')

// To:
fetch(API_BASE + '/api/...')
```

---

## 🌍 Step 5: Set Up Custom Domain (Optional)

1. Buy domain from [Namecheap.com](https://namecheap.com) (~$3-4/year)
   - Search for domain like `uconnect-za.com`
   - Add to cart and checkout

2. On Render dashboard:
   - Go to Settings → Custom Domain
   - Add your domain
   - Render gives you nameserver info
   - Update nameservers on Namecheap

3. Wait 24-48 hours for DNS to propagate

---

## 🔐 Step 6: Enable HTTPS (Automatic on Render)

✅ **Already included** — Render automatically provides SSL/TLS certificate

Your app is now secure: `https://uconnect-app.onrender.com`

---

## 📝 Important Notes

- **Free Tier Limits:**
  - 750 hours/month (30+ days of uptime)
  - Deploys sleep after 15 min of inactivity (wake in 30s)
  - 0.5GB RAM

- **Database Persistence:**
  - SQLite file stored on disk
  - Data persists between deployments
  - Backup regularly to cloud storage (Google Drive, etc.)

- **Auto-deploy:**
  - Every push to `main` branch auto-deploys
  - Check "Deploy on push" in settings

- **Logs:**
  - View in Render dashboard → Logs tab
  - Check for errors during startup

---

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| **"Build failed"** | Check logs, ensure `requirements.txt` is in root directory |
| **"Port already in use"** | Render handles this automatically |
| **"Database not found"** | First run creates it, check file permissions |
| **"CORS errors"** | Add `Flask-CORS` to handle cross-origin requests |

---

## 🚀 Next Steps

1. ✅ Deploy backend to Render (this guide)
2. ⏭️ Register domain name (Namecheap)
3. ⏭️ Configure SSL/HTTPS (Automatic on Render)
4. ⏭️ Promote and share with users!

**Your app is now mobile-first, offline-capable, and cloud-deployed!** 🎉
