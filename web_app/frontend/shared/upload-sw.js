/* 知识库上传后台任务：页面跳转/关闭后仍由 SW 内 fetch 完成 multipart 上传。 */
self.addEventListener("install", function () {
  self.skipWaiting();
});
self.addEventListener("activate", function (e) {
  e.waitUntil(self.clients.claim());
});

let uploadChain = Promise.resolve();

function notifyClients(msg) {
  return self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clients) {
    clients.forEach(function (c) {
      try {
        c.postMessage(msg);
      } catch (_) {}
    });
  });
}

self.addEventListener("message", function (event) {
  const d = event.data;
  if (!d || d.type !== "KB_UPLOAD") return;
  const buf = d.buffer;
  if (!buf) return;

  uploadChain = uploadChain.then(function () {
    return runOneUpload(d);
  });
});

function runOneUpload(d) {
  const uploadId = d.uploadId;
  const batchNonce = d.batchNonce || "";
  const token = d.token || "";
  const category = d.category || "默认知识库";
  const description = d.description || "";
  const fileName = d.fileName || "file";
  const mime = d.mime || "";
  const buf = d.buffer;

  const fd = new FormData();
  fd.append("category", category);
  fd.append("description", description);

  const blob = new Blob([buf], { type: mime || "application/octet-stream" });
  fd.append("files", blob, fileName);

  const headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;

  return fetch(new URL("/api/upload", self.location.origin).href, {
    method: "POST",
    body: fd,
    headers: headers,
  })
    .then(function (r) {
      return r.json().then(
        function (data) {
          return { r: r, data: data };
        },
        function () {
          return { r: r, data: {} };
        }
      );
    })
    .then(function (_ref) {
      const r = _ref.r;
      const data = _ref.data;
      const results = data.results || [];
      const first = results[0];
      if (!r.ok) {
        let error = "";
        const detail = data.detail;
        error = Array.isArray(detail)
          ? detail
              .map(function (x) {
                return x.msg;
              })
              .join("; ")
          : detail || r.statusText;
        error = typeof error === "string" ? error : r.statusText;
        return notifyClients({
          type: "KB_UPLOAD_DONE",
          uploadId: uploadId,
          batchNonce: batchNonce,
          fileName: fileName,
          ok: false,
          error: error,
        });
      }
      if (first && first.ok && first.queued && first.job_id) {
        return notifyClients({
          type: "KB_UPLOAD_QUEUED",
          uploadId: uploadId,
          batchNonce: batchNonce,
          fileName: fileName,
          jobId: first.job_id,
        });
      }
      if (first && first.ok) {
        return notifyClients({
          type: "KB_UPLOAD_DONE",
          uploadId: uploadId,
          batchNonce: batchNonce,
          fileName: fileName,
          ok: true,
          error: "",
        });
      }
      const err = (first && first.error) || "入库失败";
      return notifyClients({
        type: "KB_UPLOAD_DONE",
        uploadId: uploadId,
        batchNonce: batchNonce,
        fileName: fileName,
        ok: false,
        error: err,
      });
    })
    .catch(function (e) {
      return notifyClients({
        type: "KB_UPLOAD_DONE",
        uploadId: uploadId,
        batchNonce: batchNonce,
        fileName: fileName,
        ok: false,
        error: e && e.message ? e.message : String(e),
      });
    });
}
