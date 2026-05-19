import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { AppearanceProvider } from "./components/AppearanceContext";
import { AppModeProvider } from "./components/AppModeContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppearanceProvider>
        <AppModeProvider>
          <App />
        </AppModeProvider>
      </AppearanceProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
