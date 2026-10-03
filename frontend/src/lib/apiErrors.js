import { ApiError } from "../api.js";

/** Engineering-console wording for transport failures. */
export function describeApiError(error) {
  if (error instanceof ApiError && error.kind === "API_UNAVAILABLE") {
    return "The backend API is unreachable. Start the FastAPI server and retry.";
  }
  if (error instanceof ApiError && error.kind === "TIMEOUT") {
    return "The request to the backend timed out.";
  }
  return "The backend returned an error. Check the API logs.";
}
