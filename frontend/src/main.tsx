import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ToastProvider } from "./components/Feedback";
import { PreviewProvider } from "./hooks/useAudio";
import { I18nProvider } from "./i18n";
import "./index.css";
import { AppProvider } from "./store";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <AppProvider>
        <ToastProvider>
          <PreviewProvider>
            <App />
          </PreviewProvider>
        </ToastProvider>
      </AppProvider>
    </I18nProvider>
  </StrictMode>,
);
