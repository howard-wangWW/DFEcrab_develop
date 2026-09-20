//开关排序
function switchDisplayLabel(item, fallback = "") {
  if (!item) return String(fallback || "");
  const name = String(item.name || "").trim();
  const dispatch = String(item.dispatchNumber || "").trim();
  if (dispatch && /PT/i.test(dispatch) && /PT/i.test(name)) return dispatch;
  return name || dispatch || item.mrid || item.id || fallback || "";
}

function switchOrderKey(item) {
  const label = switchDisplayLabel(item)
    .toUpperCase()
    .replace(/\s+/g, "");
  const dispatch = String((item && item.dispatchNumber) || "")
    .toUpperCase()
    .replace(/\s+/g, "");
  const candidates = [label, dispatch].filter(Boolean);

  for (const value of candidates) {
    const feeder = value.match(/^F0*(\d+)$/);
    if (feeder) return [0, Number(feeder[1]), 0, 0, value];
  }

  for (const value of candidates) {
    const pt = value.match(/^[68]?([1-9])PT$/);
    if (pt || value === "PT") {
      return [1, pt ? Number(pt[1]) : 1, 0, 0, value];
    }
  }

  for (const value of candidates) {
    const cabinetNo = value.match(/^([68])(\d{2})$/);
    if (cabinetNo) {
      return [1, Number(cabinetNo[2]), 1, Number(cabinetNo[1]), value];
    }
  }

  for (const value of candidates) {
    const smallNo = value.match(/^(\d{1,2})$/);
    if (smallNo) return [1, Number(smallNo[1]), 2, 0, value];
  }

  const numeric = (label.match(/\d+/) || ["9999"])[0];
  return [2, Number(numeric), 0, 0, label];
}

function compareSwitchOrder(a, b) {
  const ak = switchOrderKey(a);
  const bk = switchOrderKey(b);
  for (let i = 0; i < Math.min(ak.length, bk.length) - 1; i += 1) {
    if (ak[i] !== bk[i]) return ak[i] - bk[i];
  }
  return String(ak[ak.length - 1]).localeCompare(String(bk[bk.length - 1]), "zh-Hans-CN");
}

module.exports = {
  compareSwitchOrder,
  switchDisplayLabel,
  switchOrderKey
};
