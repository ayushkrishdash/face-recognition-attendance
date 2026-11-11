// Captures a face for the student form. The JPEG is attached to the form's file input,
// so it travels with the normal form POST and is processed server-side, then discarded.
(() => {
  const video = document.getElementById("faceVideo");
  if (!video) return;
  const startBtn = document.getElementById("faceStart");
  const captureBtn = document.getElementById("faceCapture");
  const retakeBtn = document.getElementById("faceRetake");
  const preview = document.getElementById("facePreview");
  const input = document.getElementById("faceInput");
  const errorBox = document.getElementById("faceError");

  const showError = (msg) => { errorBox.textContent = msg; errorBox.hidden = !msg; };

  startBtn.addEventListener("click", async () => {
    showError("");
    try {
      await CameraKit.start(video);
      video.hidden = false;
      preview.hidden = true;
      startBtn.disabled = true;
      captureBtn.disabled = false;
    } catch (err) {
      showError(CameraKit.errorMessage(err));
    }
  });

  captureBtn.addEventListener("click", async () => {
    const blob = await CameraKit.capture(video);
    if (!blob) { showError("The camera is not ready yet. Try again in a moment."); return; }
    const transfer = new DataTransfer();
    transfer.items.add(new File([blob], "face.jpg", { type: "image/jpeg" }));
    input.files = transfer.files;
    preview.src = URL.createObjectURL(blob);
    preview.hidden = false;
    video.hidden = true;
    CameraKit.stop();
    captureBtn.disabled = true;
    retakeBtn.hidden = false;
    showError("");
  });

  retakeBtn.addEventListener("click", () => {
    input.value = "";
    URL.revokeObjectURL(preview.src);
    preview.hidden = true;
    retakeBtn.hidden = true;
    startBtn.disabled = false;
    startBtn.click();
  });
})();
