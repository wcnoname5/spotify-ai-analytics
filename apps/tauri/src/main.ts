import { createApp } from "vue";
import App from "./App.vue";
import SetupPage from "./SetupPage.vue";
import "./styles.css";

// The setup window (opened by open_setup_window) loads index.html#setup, so the
// same bundle mounts SetupPage instead of the dashboard.
const root = location.hash === "#setup" ? SetupPage : App;
createApp(root).mount("#app");
