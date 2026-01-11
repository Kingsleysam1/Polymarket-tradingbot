# Deploying the Polymarket MM Bot

Since this bot requires a long-running process (for WebSockets and market making loop), **Vercel is not suitable** as it is designed for short-lived serverless functions.

Instead, we recommend **Railway** or **Render**, which natively support persistent Docker applications and are very easy to use.

## Prerequisites

1.  A GitHub repository containing this code.
2.  Your Polymarket API credentials (`.env` values).

## Option 1: Deploy on Railway (Recommended)

1.  **Push your code to GitHub**.
2.  Log in to [Railway](https://railway.app/).
3.  Click **New Project** -> **Deploy from GitHub repo**.
4.  Select your repository.
5.  Railway will automatically detect the `Dockerfile` and start building.
6.  **Configure Environment Variables**:
    *   Go to the **Variables** tab in your Railway project.
    *   Add all the variables from your local `.env` file (e.g., `PRIVATE_KEY`, `CLOB_API_KEY`, `CHAIN_ID`, etc.).
    *   Set `PAPER_TRADING_MODE=true` initially to test safely.
7.  Once deployed, Railway will provide a public URL (e.g., `https://web-production-xxx.up.railway.app`).
    *   Open this URL to view your **Dashboard**.

## Option 2: Deploy on Render

1.  Log in to [Render](https://render.com/).
2.  Click **New +** -> **Web Service**.
3.  Connect your GitHub repository.
4.  Select **Docker** as the runtime.
5.  **Environment Variables**:
    *   Click **Advanced** or scroll to the Environment section.
    *   Add your `.env` keys and values.
6.  Click **Create Web Service**.

## Local Deployment (Docker)

If you have Docker installed locally:

1.  Build the image:
    ```bash
    docker build -t polymarket-bot .
    ```
2.  Run the container:
    ```bash
    docker run -p 8080:8080 --env-file polymarket/.env polymarket-bot
    ```
3.  Visit `http://localhost:8080` to see the dashboard.

## Notes

*   **Dashboard**: The dashboard is now served directly by the bot on the root URL.
*   **Security**: Never commit your `.env` file or private keys to GitHub. Use the platform's Environment Variables settings.
