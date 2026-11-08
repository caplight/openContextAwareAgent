export type Lang = 'zh' | 'en'

const translations: Record<Lang, Record<string, string>> = {
  zh: {
    // 应用
    appTitle: 'Kubernetes DevOps 助手',
    appCaption: 'DevOps 取证助手（查集群 · 查文档 · 联网搜索）',
    // 会话栏
    newChat: '新建会话',
    sessions: '会话',
    emptySessions: '暂无会话',
    untitled: '未命名会话',
    rename: '重命名',
    delete: '删除',
    confirmDelete: '确定删除该会话？',
    // 输入区
    inputPlaceholder: '问点什么，例如「我的节点状态怎么样？」',
    send: '发送',
    stop: '停止',
    // 消息操作
    copy: '复制',
    copied: '已复制',
    regenerate: '重新生成',
    edit: '编辑',
    editHint: 'Enter 发送，Esc 取消',
    // 工具调用
    toolCalling: '调用工具',
    args: '入参',
    output: '结果',
    statusRunning: '进行中',
    statusSuccess: '成功',
    statusError: '失败',
    duration: '耗时',
    // 思考
    thinking: '思考过程',
    actions: '工具调用',
    // 引用
    sources: '引用来源',
    // 主题/语言
    darkMode: '暗色',
    lightMode: '亮色',
    language: '语言',
    // 空状态
    emptyChat: '开始一段新的对话吧',
    // 错误
    streamError: '出错了',
  },
  en: {
    appTitle: 'Kubernetes DevOps Assistant',
    appCaption: 'DevOps troubleshooting (cluster · docs · web search)',
    newChat: 'New chat',
    sessions: 'Sessions',
    emptySessions: 'No conversations yet',
    untitled: 'Untitled',
    rename: 'Rename',
    delete: 'Delete',
    confirmDelete: 'Delete this session?',
    inputPlaceholder: 'Ask anything, e.g. "What is the status of my nodes?"',
    send: 'Send',
    stop: 'Stop',
    copy: 'Copy',
    copied: 'Copied',
    regenerate: 'Regenerate',
    edit: 'Edit',
    editHint: 'Enter to send, Esc to cancel',
    toolCalling: 'Calling tool',
    args: 'Arguments',
    output: 'Output',
    statusRunning: 'Running',
    statusSuccess: 'Success',
    statusError: 'Failed',
    duration: 'Duration',
    thinking: 'Thinking',
    actions: 'Actions',
    sources: 'Sources',
    darkMode: 'Dark',
    lightMode: 'Light',
    language: 'Language',
    emptyChat: 'Start a new conversation',
    streamError: 'Something went wrong',
  },
}

export function makeT(lang: Lang) {
  return (key: string): string => translations[lang][key] ?? key
}
