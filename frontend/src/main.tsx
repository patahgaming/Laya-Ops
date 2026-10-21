import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./state/auth";
import { RefreshProvider } from "./state/refresh";
import { ToastProvider } from "./state/toast";
import "./styles/global.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <RefreshProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </RefreshProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>
);
