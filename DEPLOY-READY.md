# Merged Site - DEPLOY-READY.md

## Hosting Options
### 1. GitHub Pages
- Create a repository on GitHub.
- Push your code to the repository.
- Navigate to the repository settings and enable GitHub Pages.

### 2. Cloudflare Pages
- Sign up for a Cloudflare Account and create a new project.
- Choose your Git provider and grant access.
- Select your repository and set the build command (if needed).

### 3. Netlify
- Sign up for a Netlify account.
- Drag and drop your project folder in the Netlify UI.
- Configure your settings if needed (custom domain, build settings).

### 4. Vercel
- Sign up and connect to your Git repository.
- Deploy through the Vercel dashboard.

## Custom Domain Setup
To link a custom domain:
- Create a DNS A/CNAME Record pointing your domain to your hosting.
- Follow your provider's instructions to set an SSL certificate.

## Backend Hosting (if needed)
### Python Hosting
For a backend to handle dynamic requests (i.e., cpshop_http.py):
- Use a VPS, Render, Railway, or Fly.io.
- Ensure to configure environment variables properly.
- Use a SQLite file for persistence.

## Required Files for Deployment
- index.html
- logos.html
- privacy.html
- robots.txt
- sitemap.xml
- all files in assets/

## Post-deploy Checklist
- Ensure HTTPS is running.
- Check that all pages (index/privacy/logos) load without errors.
- Verify all interactive features respond correctly (e.g., order endpoint).
- Confirm Persian fonts load correctly.

## Notes
Ensure this static site handles UTF-8 headers and is RTL-compatible.

**Finalize and test your settings to ensure a smooth deployment!**
