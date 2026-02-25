/**
 * Phase 2 E2E: Review Sessions, Marks, Progress, and Undo/Redo APIs.
 *
 * Tests the review workflow: creating sessions, tracking cursor position,
 * adding marks (viewed/bookmarked/flagged), querying session progress,
 * and the undo/redo stack for batch operations.
 */
import { test, expect } from "../fixtures/links-db";
import { FAMILIES, MINIMAL_LINKS } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";

test.describe("Sessions, Marks & Undo/Redo API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. POST /api/links/review-sessions ──────────────────

  test("POST /api/links/review-sessions creates a session", async ({
    apiContext,
  }) => {
    const res = await apiContext.post("/api/links/review-sessions", {
      data: {
        family_id: FAMILIES.indebtedness,
        reviewer: "test-user",
        filter: { confidence_tier: "high" },
      },
    });
    expectOk(res);
    const body = await res.json();

    expect(body.session_id).toBeDefined();
    expect(body.family_id).toBe(FAMILIES.indebtedness);
    expect(body.reviewer).toBe("test-user");
    expect(body).toHaveProperty("cursor_position");
    expect(body).toHaveProperty("created_at");
    // New session starts at position 0
    expect(body.cursor_position).toBe(0);
  });

  // ── 2. PATCH /api/links/review-sessions/{id} ───────────

  test("PATCH /api/links/review-sessions/{id} updates cursor position", async ({
    apiContext,
  }) => {
    // Create a session first
    const createRes = await apiContext.post("/api/links/review-sessions", {
      data: {
        family_id: FAMILIES.indebtedness,
        reviewer: "test-user",
      },
    });
    expectOk(createRes);
    const session = await createRes.json();

    // Advance the cursor
    const patchRes = await apiContext.patch(
      `/api/links/review-sessions/${session.session_id}`,
      { data: { cursor_position: 5 } },
    );
    expectOk(patchRes);
    const updated = await patchRes.json();

    expect(updated.session_id).toBe(session.session_id);
    expect(updated.cursor_position).toBe(5);

    // Advance again to verify incremental updates
    const patchRes2 = await apiContext.patch(
      `/api/links/review-sessions/${session.session_id}`,
      { data: { cursor_position: 8 } },
    );
    expectOk(patchRes2);
    const updated2 = await patchRes2.json();
    expect(updated2.cursor_position).toBe(8);
  });

  // ── 3. POST /api/links/review-marks ─────────────────────

  test("POST /api/links/review-marks adds marks (viewed/bookmarked/flagged)", async ({
    apiContext,
  }) => {
    // Create a session
    const sessionRes = await apiContext.post("/api/links/review-sessions", {
      data: {
        family_id: FAMILIES.indebtedness,
        reviewer: "test-user",
      },
    });
    expectOk(sessionRes);
    const session = await sessionRes.json();

    // Add a "viewed" mark
    const viewedRes = await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[0].link_id, // LINK-001
        type: "viewed",
      },
    });
    expectOk(viewedRes);
    const viewed = await viewedRes.json();
    expect(viewed.mark_id).toBeDefined();
    expect(viewed.type).toBe("viewed");
    expect(viewed.link_id).toBe(MINIMAL_LINKS[0].link_id);

    // Add a "bookmarked" mark
    const bookmarkRes = await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[1].link_id, // LINK-002
        type: "bookmark",
      },
    });
    expectOk(bookmarkRes);
    const bookmark = await bookmarkRes.json();
    expect(bookmark.mark_id).toBeDefined();
    expect(bookmark.type).toBe("bookmark");

    // Add a "flagged" mark
    const flagRes = await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[2].link_id, // LINK-003
        type: "flagged",
        notes: "Confidence seems too high for this heading",
      },
    });
    expectOk(flagRes);
    const flagged = await flagRes.json();
    expect(flagged.mark_id).toBeDefined();
    expect(flagged.type).toBe("flagged");
    expect(flagged.notes).toBe("Confidence seems too high for this heading");
  });

  // ── 4. GET /api/links/review-marks?type=bookmark ────────

  test("GET /api/links/review-marks?type=bookmark returns bookmarks", async ({
    apiContext,
  }) => {
    // Create session and add bookmarks
    const sessionRes = await apiContext.post("/api/links/review-sessions", {
      data: {
        family_id: FAMILIES.indebtedness,
        reviewer: "test-user",
      },
    });
    expectOk(sessionRes);
    const session = await sessionRes.json();

    // Bookmark two links
    await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[0].link_id,
        type: "bookmark",
      },
    });
    await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[4].link_id, // LINK-005
        type: "bookmark",
      },
    });

    // Also add a non-bookmark mark (should not appear)
    await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[2].link_id,
        type: "viewed",
      },
    });

    // Query only bookmarks
    const res = await apiContext.get("/api/links/review-marks?type=bookmark");
    expectOk(res);
    const body = await res.json();

    expect(body.marks).toBeDefined();
    expect(Array.isArray(body.marks)).toBe(true);
    expect(body.marks.length).toBeGreaterThanOrEqual(2);

    // All returned marks should be bookmarks
    for (const mark of body.marks) {
      expect(mark.type).toBe("bookmark");
      expect(mark).toHaveProperty("mark_id");
      expect(mark).toHaveProperty("link_id");
    }

    // Our specific bookmarked links should be present
    const linkIds = body.marks.map((m: Record<string, unknown>) => m.link_id);
    expect(linkIds).toContain(MINIMAL_LINKS[0].link_id);
    expect(linkIds).toContain(MINIMAL_LINKS[4].link_id);
  });

  // ── 5. GET /api/links/review-sessions/{id}/progress ─────

  test("GET /api/links/review-sessions/{id}/progress returns session progress", async ({
    apiContext,
  }) => {
    // Create a session scoped to the indebtedness family
    const sessionRes = await apiContext.post("/api/links/review-sessions", {
      data: {
        family_id: FAMILIES.indebtedness,
        reviewer: "test-user",
      },
    });
    expectOk(sessionRes);
    const session = await sessionRes.json();

    // Mark a couple of links as viewed
    await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[0].link_id, // LINK-001 (indebtedness)
        type: "viewed",
      },
    });
    await apiContext.post("/api/links/review-marks", {
      data: {
        session_id: session.session_id,
        link_id: MINIMAL_LINKS[1].link_id, // LINK-002 (indebtedness)
        type: "viewed",
      },
    });

    // Query progress
    const res = await apiContext.get(
      `/api/links/review-sessions/${session.session_id}/progress`,
    );
    expectOk(res);
    const body = await res.json();

    expect(body.session_id).toBe(session.session_id);
    expect(body).toHaveProperty("total_links");
    expect(body).toHaveProperty("reviewed_count");
    expect(body).toHaveProperty("remaining_count");
    expect(body).toHaveProperty("percent_complete");

    expect(typeof body.total_links).toBe("number");
    expect(body.reviewed_count).toBeGreaterThanOrEqual(2);
    expect(body.total_links).toBeGreaterThan(0);
    expect(body.remaining_count).toBe(body.total_links - body.reviewed_count);
    expect(body.percent_complete).toBeGreaterThan(0);
    expect(body.percent_complete).toBeLessThanOrEqual(100);
  });

  // ── 6. POST /api/links/undo ─────────────────────────────

  test("POST /api/links/undo reverses a batch unlink", async ({
    apiContext,
  }) => {
    // First, perform a batch unlink so there is something to undo
    const unlinkRes = await apiContext.post("/api/links/batch", {
      data: {
        action: "unlink",
        link_ids: [MINIMAL_LINKS[0].link_id, MINIMAL_LINKS[1].link_id],
        reason: "Testing undo functionality",
      },
    });
    expectOk(unlinkRes);
    const unlinkBody = await unlinkRes.json();
    expect(unlinkBody).toHaveProperty("batch_id");

    // Verify links are now unlinked
    const checkRes = await apiContext.get(
      `/api/links/${MINIMAL_LINKS[0].link_id}`,
    );
    expectOk(checkRes);
    const unlinked = await checkRes.json();
    expect(unlinked.status).toBe("unlinked");

    // Undo the batch unlink
    const undoRes = await apiContext.post("/api/links/undo", {
      data: { batch_id: unlinkBody.batch_id },
    });
    expectOk(undoRes);
    const undoBody = await undoRes.json();

    expect(undoBody).toHaveProperty("undone_batch_id");
    expect(undoBody.undone_batch_id).toBe(unlinkBody.batch_id);
    expect(undoBody).toHaveProperty("restored_count");
    expect(undoBody.restored_count).toBe(2);

    // Verify the links are restored to their original status
    const restoredRes = await apiContext.get(
      `/api/links/${MINIMAL_LINKS[0].link_id}`,
    );
    expectOk(restoredRes);
    const restored = await restoredRes.json();
    expect(restored.status).toBe("active");
  });

  // ── 7. POST /api/links/redo ─────────────────────────────

  test("POST /api/links/redo replays an undone action", async ({
    apiContext,
  }) => {
    // Perform a batch unlink
    const unlinkRes = await apiContext.post("/api/links/batch", {
      data: {
        action: "unlink",
        link_ids: [MINIMAL_LINKS[0].link_id],
        reason: "Testing redo functionality",
      },
    });
    expectOk(unlinkRes);
    const unlinkBody = await unlinkRes.json();

    // Undo it
    const undoRes = await apiContext.post("/api/links/undo", {
      data: { batch_id: unlinkBody.batch_id },
    });
    expectOk(undoRes);

    // Verify link is restored
    const afterUndoRes = await apiContext.get(
      `/api/links/${MINIMAL_LINKS[0].link_id}`,
    );
    expectOk(afterUndoRes);
    const afterUndo = await afterUndoRes.json();
    expect(afterUndo.status).toBe("active");

    // Redo: replay the undone unlink
    const redoRes = await apiContext.post("/api/links/redo", {
      data: { batch_id: unlinkBody.batch_id },
    });
    expectOk(redoRes);
    const redoBody = await redoRes.json();

    expect(redoBody).toHaveProperty("redone_batch_id");
    expect(redoBody.redone_batch_id).toBe(unlinkBody.batch_id);
    expect(redoBody).toHaveProperty("affected_count");
    expect(redoBody.affected_count).toBe(1);

    // Verify link is unlinked again after redo
    const afterRedoRes = await apiContext.get(
      `/api/links/${MINIMAL_LINKS[0].link_id}`,
    );
    expectOk(afterRedoRes);
    const afterRedo = await afterRedoRes.json();
    expect(afterRedo.status).toBe("unlinked");
  });
});
