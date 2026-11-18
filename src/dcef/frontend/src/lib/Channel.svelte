<script lang="ts">
    import { isDateDifferent } from "../js/helpers";
    import { fetchMessages } from "../js/stores/api";
    import { getGuildState } from "../js/stores/guildState.svelte";
    import { getLayoutState } from "../js/stores/layoutState.svelte";
    import { showMessageBarPlaceholder } from "../js/stores/settingsStore.svelte";
    import DateSeparator from "./DateSeparator.svelte";
    import InfiniteScroll3 from "./InfiniteScroll3.svelte";
    import ChannelStart from "./message/ChannelStart.svelte";
    import Message from "./message/Message.svelte";

    interface MyProps {
        archiveRevision: number | null
    }

    let { archiveRevision }: MyProps = $props()

    const guildState = getGuildState()
    const layoutState = getLayoutState()

    let apiGuildId = $derived(guildState.guildId ? guildState.guildId : "000000000000000000000000")
    let apiChannelId = $derived(guildState.channelId)


    async function fetchMessagesWrapper(direction: "before" | "after" | "around" | "first" | "last", messageId: string | null = null, limit: number) {
        return fetchMessages(apiGuildId, apiChannelId, direction, messageId, limit)
    }

    function replaceViewportState(messageId: string, offset: number) {
        return guildState.replaceViewportState("channel", messageId, offset)
    }
</script>

{#snippet channelStartSnippet(message)}
    <ChannelStart channelName={message.channelName} isThread={false} messageAuthor={message.author} />
{/snippet}

{#snippet emptyChannelSnippet()}
    <div class="empty-channel" role="status">
        <h2>No archived messages yet</h2>
        <p>This channel is listed in the archive, but no messages are available to display.</p>
        <p>With capture enabled in the Discord tab, open this conversation and scroll to load messages, then refresh the viewer.</p>
    </div>
{/snippet}

{#snippet channelEndSnippet(index, message, previousMessage)}
    <div data-messageid="last">
        this is the end of the channel
    </div>
{/snippet}

{#snippet renderMessageSnippet2(message, previousMessage)}
    <div data-messageid={message._id}>
        {#if message._id === "first"}
            <div>channel start</div>
        {:else if message._id === "last"}
            <div>channel end</div>
        {:else}
            {#if isDateDifferent(previousMessage, message)}
                <DateSeparator messageId={message._id} />
            {/if}
            <Message message={message} previousMessage={previousMessage} />
        {/if}
    </div>
{/snippet}

<div class="channel-wrapper" class:threadshown={layoutState.threadshown}>
    <div class="channel" >
        {#if apiChannelId}
            <!-- TODO: support change of selectedMessageId without rerender -->
            {#key guildState.channelMessageId}
                {#key apiChannelId}
                    <InfiniteScroll3
                        fetchMessages={fetchMessagesWrapper}
                        {archiveRevision}
                        scrollToMessageId={guildState.channelMessageId}
                        scrollOffset={guildState.channelMessageOffset}
                        onViewportChange={replaceViewportState}
                        snippetMessage={renderMessageSnippet2}
                        channelStartSnippet={channelStartSnippet}
                        emptySnippet={emptyChannelSnippet}
                    />
                {/key}
            {/key}
        {/if}
    </div>
    {#if $showMessageBarPlaceholder}
        <div class="message-composer-placeholder" aria-hidden="true"></div>
    {/if}
</div>


<style>
    .empty-channel {
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        min-height: 100%;
        box-sizing: border-box;
        padding: 32px;
        text-align: center;
        color: #b5bac1;
    }
    .empty-channel h2 {
        color: #f2f3f5;
        margin: 0 0 12px;
    }
    .empty-channel p {
        max-width: 560px;
        margin: 4px 0;
    }
    .channel-wrapper {
        display: flex;
        flex-direction: column;
        height: 100%;
        background-color: #313338;
        overflow: hidden;
    }

    .threadshown {
        border-bottom-right-radius: 8px;
    }
    .channel {
        flex: 1;
        min-height: 0;
        background-color: #313338;
    }
    .message-composer-placeholder {
        flex: 0 0 56px;
        margin: 12px 12px 16px;
        border-radius: 8px;
        background-color: #232428;
    }
</style>
