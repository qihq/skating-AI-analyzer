import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { CapabilityProvider } from "./analysis-v2/CapabilityContext";
import { AppearanceProvider } from "./components/AppearanceContext";
import { AppModeProvider } from "./components/AppModeContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppearanceProvider>
        <CapabilityProvider>
          <AppModeProvider>
            <App />
          </AppModeProvider>
        </CapabilityProvider>
      </AppearanceProvider>
    </BrowserRouter>
  </React.StrictMode>,
);

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
  });
}
