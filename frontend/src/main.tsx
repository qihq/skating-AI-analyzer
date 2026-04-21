import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { AppModeProvider } from "./components/AppModeContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <AppModeProvider>
        <App />
      </AppModeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
