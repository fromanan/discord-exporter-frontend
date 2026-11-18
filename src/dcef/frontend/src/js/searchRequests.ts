export type SearchDirection = "before" | "after" | "around" | "first" | "last";

export function userSearchToken(kind: "from" | "mentions", userId: string): string {
    if (!/^[0-9]{1,24}$/.test(userId)) throw new Error("Invalid user ID");
    return `${kind}:<@${userId.replace(/^0+/, "") || "0"}> `;
}

export function searchParameters(guildId: string, prompt: string, direction: SearchDirection = "first", messageId: string | null = null, limit = 50): URLSearchParams {
    const size = Number.isFinite(limit) ? Math.min(100, Math.max(1, Math.trunc(limit))) : 50;
    const parameters = new URLSearchParams({ guild_id: guildId, prompt, limit: String(size) });
    if (direction === "first") parameters.set("next_page_cursor", "0");
    else if (direction === "last" || messageId === "last") parameters.set("prev_page_cursor", "999999999999999999999999");
    else {
        if (messageId === null || !/^[0-9]{1,24}$/.test(messageId)) throw new Error("Invalid search cursor");
        parameters.set(direction === "before" ? "prev_page_cursor" : direction === "after" ? "next_page_cursor" : "around_page_cursor", messageId);
    }
    return parameters;
}

export function requestBatches<T>(values: T[], pageSize = 100): T[][] {
    if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) throw new Error("Invalid request page size");
    const pages: T[][] = [];
    for (let index = 0; index < values.length; index += pageSize) pages.push(values.slice(index, index + pageSize));
    return pages;
}
