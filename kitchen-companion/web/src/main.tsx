import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

// No StrictMode: its double-mounted effects would open and drop a WebRTC call on every dev reload.
createRoot(document.getElementById("root")!).render(<App />);
