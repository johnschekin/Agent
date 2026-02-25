/**
 * Job polling helper — waits for a job to reach a terminal state.
 *
 * Polls GET /api/links/jobs/{job_id} at the given interval until the job
 * reaches "completed", "failed", or "cancelled", or until the timeout expires.
 */
import type { APIRequestContext } from "@playwright/test";

export type TerminalStatus = "completed" | "failed" | "cancelled";

export interface WaitForJobOptions {
  /** Polling interval in ms (default: 500). */
  pollIntervalMs?: number;
  /** Maximum wait time in ms (default: 15000). */
  timeoutMs?: number;
}

export interface JobResult {
  status: TerminalStatus;
  result_json?: string;
  error_message?: string;
  [key: string]: unknown;
}

const TERMINAL_STATUSES = new Set<string>([
  "completed",
  "failed",
  "cancelled",
]);

/**
 * Poll a job until it reaches a terminal state.
 *
 * @param api - Playwright APIRequestContext
 * @param jobId - The job_id to poll
 * @param options - Polling and timeout configuration
 * @returns The final job record
 * @throws Error if the job does not reach a terminal state within the timeout
 */
export async function waitForJob(
  api: APIRequestContext,
  jobId: string,
  options?: WaitForJobOptions,
): Promise<JobResult> {
  const pollMs = options?.pollIntervalMs ?? 500;
  const timeoutMs = options?.timeoutMs ?? 15_000;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const res = await api.get(`/api/links/jobs/${jobId}`);
    if (!res.ok()) {
      throw new Error(
        `Failed to fetch job ${jobId}: ${res.status()} ${await res.text()}`,
      );
    }

    const job = (await res.json()) as JobResult;
    if (TERMINAL_STATUSES.has(job.status)) {
      return job;
    }

    await new Promise((resolve) => setTimeout(resolve, pollMs));
  }

  throw new Error(
    `Job ${jobId} did not reach terminal state within ${timeoutMs}ms`,
  );
}
