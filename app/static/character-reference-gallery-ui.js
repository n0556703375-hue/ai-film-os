(() => {
  const originalOpenAsset = window.openAsset;

  function flattenGroups(groups) {
    const entries = [];
    Object.entries(groups || {}).forEach(([viewType, expressions]) => {
      Object.entries(expressions || {}).forEach(([expression, references]) => {
        entries.push({ viewType, expression, references: references || [] });
      });
    });
    return entries;
  }

  function renderReferenceGallery(assetId, groups) {
    const entries = flattenGroups(groups);
    if (!entries.length) return "";

    return `<div class="workspace-section" style="margin-top:15px" data-character-reference-gallery>
      <h3>רפרנסים מאושרים לפי זווית והבעה</h3>
      ${entries.map(({ viewType, expression, references }) => `
        <section class="reference-group">
          <h4>${esc(viewType)} · ${esc(expression)}</h4>
          <div class="reference-grid">
            ${references.map((reference) => `
              <div class="card">
                <img src="/api/assets/${assetId}/references/${reference.id}/image"
                  alt="${esc(viewType)} · ${esc(expression)}"
                  style="width:100%;aspect-ratio:3/4;object-fit:cover;border-radius:10px"
                  onerror="this.classList.add('image-error')">
                <div class="meta">${esc(reference.model || "רפרנס מאושר")}</div>
                <a href="/api/assets/${assetId}/references/${reference.id}/image" target="_blank" rel="noopener">פתיחת התמונה</a>
              </div>`).join("")}
          </div>
        </section>`).join("")}
    </div>`;
  }

  async function appendReferenceGallery(assetId) {
    const data = await api(`/api/assets/${assetId}/references/grouped`);
    const html = renderReferenceGallery(assetId, data.groups);
    if (!html) return;
    const content = $("modalContent");
    if (content && !content.querySelector("[data-character-reference-gallery]")) {
      content.insertAdjacentHTML("beforeend", html);
    }
  }

  window.openAsset = async function openAssetWithGroupedReferences(assetId) {
    await originalOpenAsset(assetId);
    try {
      await appendReferenceGallery(assetId);
    } catch (error) {
      console.warn("Unable to load grouped character references", error);
    }
  };

  window.characterReferenceGallery = {
    flattenGroups,
    renderReferenceGallery,
  };
})();
