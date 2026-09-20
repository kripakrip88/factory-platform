import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";

/**
 * Render a message timestamp the way mail clients do: time for today,
 * weekday for the last week, date beyond that.
 */
export function formatMessageDate(value) {
    if (!value) {
        return "";
    }
    const dt = deserializeDateTime(value);
    if (!dt || !dt.isValid) {
        return "";
    }
    const now = dt.constructor.now();
    if (dt.hasSame(now, "day")) {
        return dt.toFormat("HH:mm");
    }
    if (now.diff(dt, "days").days < 7) {
        return dt.toFormat("ccc HH:mm");
    }
    return formatDateTime(dt, { format: "dd MMM yyyy" });
}

/** Strip the angle-bracket address, keeping the display name when there is one. */
export function senderName(emailFrom) {
    if (!emailFrom) {
        return _t("(unknown sender)");
    }
    const match = emailFrom.match(/^\s*"?([^"<]*?)"?\s*<[^>]+>\s*$/);
    if (match && match[1].trim()) {
        return match[1].trim();
    }
    return emailFrom.trim();
}

/** Format a byte count for display. */
export function formatSize(bytes) {
    if (!bytes) {
        return "";
    }
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit++;
    }
    return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
