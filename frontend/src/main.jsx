import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./index.css";
import ClinicianApp from "./clinician/ClinicianApp.jsx";
import EngineeringConsole from "./engineering/EngineeringConsole.jsx";

// Two separate application surfaces:
//   /             -> clinician referral assistant
//   /engineering  -> X-Verba Governance & Review Console
const isEngineering = window.location.pathname.replace(/\/+$/, "") === "/engineering";

document.title = isEngineering
  ? "X-Verba Governance & Review Console"
  : "X-Verba Healthcare Referral Agent";

createRoot(document.getElementById("root")).render(
  <StrictMode>{isEngineering ? <EngineeringConsole /> : <ClinicianApp />}</StrictMode>,
);
