import React from "react";
import ReactDOM from "react-dom/client";
import { GoogleOAuthProvider } from "@react-oauth/google";
import { BrowserRouter } from "react-router-dom";

import App from "./App.jsx";
import "./index.css";
import "./app-mobile.css";

// OAuth Client ID is public browser configuration. Keep a fallback so an
// accidentally omitted production .env file cannot remove the Google button.
const googleClientId =
  import.meta.env.VITE_GOOGLE_CLIENT_ID ??
  "303459689220-bkuu4frgrdkil3mcp8632th1j105kkv5.apps.googleusercontent.com";

const app = (
  <BrowserRouter>
    <App />
  </BrowserRouter>
);

ReactDOM.createRoot(document.getElementById("root")).render(
  googleClientId ? (
    <GoogleOAuthProvider clientId={googleClientId}>
      {app}
    </GoogleOAuthProvider>
  ) : (
    app
  ),
);
