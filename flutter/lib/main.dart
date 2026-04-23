import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:bitsdojo_window/bitsdojo_window.dart';
import 'package:window_manager/window_manager.dart';

const _icons = _Icons();
const String _caret = '▾';

class _Icons {
  const _Icons();
  final String chat = '💬';
  final String heart = '💗';
  final String briefcase = '💼';
  final String bolt = '⚡';
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();

  const options = WindowOptions(alwaysOnTop: true);
  windowManager.waitUntilReadyToShow(options, () async {
    await windowManager.show();
    await windowManager.focus();
    await windowManager.setAlwaysOnTop(true);
  });

  runApp(const ReplyCopilotApp());

  doWhenWindowReady(() async {
    const initialSize = Size(560, 640);
    appWindow
      ..minSize = initialSize
      ..size = initialSize
      ..title = 'SmoothTalker';
    appWindow.show();
    await windowManager.setAlwaysOnTop(true);
  });
}

enum Role { crush, colleague }

class _RecentThread {
  const _RecentThread({
    required this.threadId,
    required this.summary,
    required this.updatedAt,
  });

  final String threadId;
  final String summary;
  final DateTime? updatedAt;

  factory _RecentThread.fromJson(Map<String, dynamic> json) {
    return _RecentThread(
      threadId: json['thread_id']?.toString() ?? '',
      summary: json['summary']?.toString() ?? '',
      updatedAt: DateTime.tryParse(json['updated_at']?.toString() ?? ''),
    );
  }
}

class ReplyCopilotApp extends StatelessWidget {
  const ReplyCopilotApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SmoothTalker',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2563EB)),
        useMaterial3: true,
        fontFamily: 'Inter',
      ),
      home: const ReplyHomePage(),
    );
  }
}

class ReplyHomePage extends StatefulWidget {
  const ReplyHomePage({super.key});

  @override
  State<ReplyHomePage> createState() => _ReplyHomePageState();
}

class _ReplyHomePageState extends State<ReplyHomePage> {
  Role _role = Role.crush;
  bool _isGenerating = false;
  static const String _readyMessage = 'Ready. Select and copy text, then click Generate.';
  static const String _userId = 'flutter-local-user';
  final Map<Role, List<String>> _roleOptions = {
    Role.crush: const [],
    Role.colleague: const [],
  };
  final Map<Role, Map<String, dynamic>?> _roleMeta = {
    Role.crush: null,
    Role.colleague: null,
  };
  final Map<Role, String> _roleStatus = {
    Role.crush: _readyMessage,
    Role.colleague: _readyMessage,
  };
  final Map<Role, String?> _roleSessionIds = {
    Role.crush: null,
    Role.colleague: null,
  };
  final Map<Role, List<_RecentThread>> _recentThreads = {
    Role.crush: const [],
    Role.colleague: const [],
  };
  final Map<Role, bool> _isLoadingThreads = {
    Role.crush: false,
    Role.colleague: false,
  };
  final Map<Role, String?> _threadLoadErrors = {
    Role.crush: null,
    Role.colleague: null,
  };
  late final Map<Role, TextEditingController> _threadControllers;
  http.Client? _activeClient;
  bool _didCancel = false;
  Role? _generationRole;

  static const String _apiBase = 'http://127.0.0.1:8080';

  @override
  void initState() {
    super.initState();
    _threadControllers = {
      Role.crush: TextEditingController(text: 'crush-main'),
      Role.colleague: TextEditingController(text: 'colleague-main'),
    };
  }

  @override
  void dispose() {
    for (final controller in _threadControllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  String _threadIdForRole(Role role) => _threadControllers[role]?.text.trim() ?? '';

  String _buildNewThreadId(Role role) {
    final now = DateTime.now();
    final prefix = role == Role.colleague ? 'colleague' : 'crush';
    return '$prefix-${now.year}${_twoDigits(now.month)}${_twoDigits(now.day)}-${_twoDigits(now.hour)}${_twoDigits(now.minute)}${_twoDigits(now.second)}';
  }

  String _twoDigits(int value) => value.toString().padLeft(2, '0');

  void _activateThread(Role role, String threadId, {required String status}) {
    final controller = _threadControllers[role];
    if (controller == null) return;

    setState(() {
      controller.text = threadId;
      controller.selection = TextSelection.collapsed(offset: threadId.length);
      _roleOptions[role] = const [];
      _roleMeta[role] = null;
      _roleSessionIds[role] = null;
      _roleStatus[role] = status;
    });
  }

  void _startNewThread() {
    final role = _role;
    final threadId = _buildNewThreadId(role);
    _activateThread(role, threadId, status: 'Started a new ${_labelForRole(role)} thread.');
  }

  Future<List<_RecentThread>> _fetchRecentThreads({
    Role? role,
    bool showErrors = false,
  }) async {
    final targetRole = role ?? _role;
    if (_isLoadingThreads[targetRole] == true) {
      return _recentThreads[targetRole] ?? const <_RecentThread>[];
    }

    setState(() {
      _isLoadingThreads[targetRole] = true;
      _threadLoadErrors[targetRole] = null;
    });

    try {
      final response = await http
          .post(
            Uri.parse('$_apiBase/v1/threads:list'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'role': targetRole.name,
              'user_id': _userId,
              'limit': 12,
            }),
          )
          .timeout(const Duration(seconds: 15));

      if (response.statusCode != 200) {
        throw Exception('API error (${response.statusCode})');
      }

      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      final threads = (decoded['threads'] as List<dynamic>? ?? const <dynamic>[])
          .map((item) => _RecentThread.fromJson(item as Map<String, dynamic>))
          .where((thread) => thread.threadId.isNotEmpty)
          .toList();

      if (!mounted) return threads;
      setState(() {
        _recentThreads[targetRole] = threads;
        _isLoadingThreads[targetRole] = false;
        _threadLoadErrors[targetRole] = null;
      });
      return threads;
    } catch (error) {
      if (!mounted) {
        return _recentThreads[targetRole] ?? const <_RecentThread>[];
      }
      setState(() {
        _isLoadingThreads[targetRole] = false;
        _threadLoadErrors[targetRole] = error.toString();
      });
      if (showErrors) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to load recent threads: $error'),
            duration: const Duration(milliseconds: 1600),
          ),
        );
      }
      return _recentThreads[targetRole] ?? const <_RecentThread>[];
    }
  }

  Future<void> _openRecentThreadsSheet() async {
    final role = _role;
    await _fetchRecentThreads(role: role, showErrors: true);
    if (!mounted) return;

    final threads = _recentThreads[role] ?? const <_RecentThread>[];
    final errorText = _threadLoadErrors[role];
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      backgroundColor: Colors.white,
      builder: (sheetContext) {
        return _RecentThreadsSheet(
          palette: role == Role.colleague ? _Palette.colleague : _Palette.crush,
          roleLabel: _labelForRole(role),
          currentThreadId: _threadIdForRole(role),
          threads: threads,
          errorText: errorText,
          onSelect: (threadId) {
            Navigator.of(sheetContext).pop();
            _activateThread(role, threadId, status: 'Switched to thread $threadId.');
          },
          onDelete: (threadId) {
            Navigator.of(sheetContext).pop();
            _deleteThread(threadId);
          },
        );
      },
    );
  }

  Future<void> _deleteThread(String threadId) async {
    final role = _role;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('Delete Thread?'),
          content: Text('Delete "$threadId" and its saved thread memory for ${_labelForRole(role)}?'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFFDC2626)),
              child: const Text('Delete'),
            ),
          ],
        );
      },
    );

    if (confirmed != true || !mounted) return;

    try {
      final response = await http
          .post(
            Uri.parse('$_apiBase/v1/threads:delete'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'thread_id': threadId,
              'role': role.name,
              'user_id': _userId,
            }),
          )
          .timeout(const Duration(seconds: 15));

      if (response.statusCode != 200) {
        throw Exception('API error (${response.statusCode})');
      }

      final threads = await _fetchRecentThreads(role: role);
      if (!mounted) return;

      if (_threadIdForRole(role) == threadId) {
        if (threads.isNotEmpty) {
          _activateThread(role, threads.first.threadId, status: 'Deleted $threadId and switched to ${threads.first.threadId}.');
        } else {
          _activateThread(role, _buildNewThreadId(role), status: 'Deleted $threadId and started a new thread.');
        }
      } else {
        setState(() {
          _roleStatus[role] = 'Deleted thread $threadId.';
        });
      }

      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Deleted thread $threadId'),
          duration: const Duration(milliseconds: 1200),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _roleStatus[role] = 'Failed to delete thread $threadId.';
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to delete thread $threadId: $error'),
          duration: const Duration(milliseconds: 1600),
        ),
      );
    }
  }

  Future<void> _handleGenerate() async {
    if (_isGenerating) return;
    final role = _role;
    final threadId = _threadIdForRole(role);
    setState(() {
      _isGenerating = true;
      _generationRole = role;
      _roleStatus[role] = 'Capturing clipboard text...';
      _roleOptions[role] = const [];
      _roleMeta[role] = null;
      _roleSessionIds[role] = null;
      _didCancel = false;
    });

    if (threadId.isEmpty) {
      setState(() {
        _isGenerating = false;
        _generationRole = null;
        _roleStatus[role] = 'Thread ID is required.';
        _activeClient = null;
      });
      return;
    }

    final clipboardData = await Clipboard.getData(Clipboard.kTextPlain);
    final text = clipboardData?.text?.trim() ?? '';

    if (text.isEmpty) {
      setState(() {
        _isGenerating = false;
        _generationRole = null;
        _roleStatus[role] = 'No text detected on clipboard. Copy text first.';
        _activeClient = null;
      });
      return;
    }

    setState(() {
      _roleStatus[role] = 'Holup, Let me cook...';
    });

    final client = http.Client();
    _activeClient = client;

    try {
      final uri = Uri.parse('$_apiBase/v1/replies:generate');
      final response = await client
          .post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'incoming_text': text,
              'role': role.name,
              'thread_id': threadId,
              'user_id': _userId,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (response.statusCode != 200) {
        setState(() {
          _roleStatus[role] = 'API error (${response.statusCode}): ${response.body}';
          _isGenerating = false;
          _generationRole = null;
          _activeClient = null;
        });
        return;
      }

      final decoded = jsonDecode(response.body) as Map<String, dynamic>;
      final options = (decoded['options'] as List<dynamic>? ?? []).map((e) => e.toString()).toList();
      if (_didCancel || !mounted) {
        _activeClient = null;
        return;
      }
      setState(() {
        _roleOptions[role] = options;
        _roleSessionIds[role] = decoded['session_id']?.toString();
        _roleMeta[role] = decoded['meta'] as Map<String, dynamic>?;
        _roleStatus[role] = options.isEmpty
            ? 'API returned no options.'
            : 'Role ${_labelForRole(role)} - ${options.length} option(s) ready.';
        _isGenerating = false;
        _generationRole = null;
        _activeClient = null;
      });
      await _fetchRecentThreads(role: role);
    } catch (error) {
      if (_didCancel || !mounted) {
        _activeClient = null;
        return;
      }
      setState(() {
        _roleStatus[role] = 'Error: $error';
        _isGenerating = false;
        _generationRole = null;
        _activeClient = null;
      });
    } finally {
      client.close();
    }
  }

  void _cancelGeneration() {
    final client = _activeClient;
    if (!_isGenerating || client == null) return;
    _didCancel = true;
    client.close();
    setState(() {
      if (_generationRole != null) {
        _roleStatus[_generationRole!] = 'Generation stopped.';
      }
      _isGenerating = false;
      _generationRole = null;
      _activeClient = null;
    });
  }

  Future<void> _handleCopyOption(String text, int index) async {
    final role = _role;
    final sessionId = _roleSessionIds[role];
    final threadId = _threadIdForRole(role);

    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Reply copied to clipboard'), duration: Duration(milliseconds: 900)),
    );

    if (sessionId == null || sessionId.isEmpty || threadId.isEmpty) {
      return;
    }

    try {
      final response = await http
          .post(
            Uri.parse('$_apiBase/v1/replies:select'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'session_id': sessionId,
              'thread_id': threadId,
              'option_index': index,
              'user_id': _userId,
            }),
          )
          .timeout(const Duration(seconds: 15));

      if (!mounted) return;
      setState(() {
        _roleStatus[role] = response.statusCode == 200
            ? 'Copied option ${index + 1} and saved it to thread memory.'
            : 'Copied option ${index + 1}, but feedback sync failed.';
      });
      if (response.statusCode == 200) {
        await _fetchRecentThreads(role: role);
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _roleStatus[role] = 'Copied option ${index + 1}, but feedback sync failed.';
      });
    }
  }

  void _switchRole(Role role) {
    if (_role == role) return;
    setState(() {
      _role = role;
    });
  }

  @override
  Widget build(BuildContext context) {
    final palette = _role == Role.colleague ? _Palette.colleague : _Palette.crush;
    final options = _roleOptions[_role] ?? const <String>[];
    final meta = _roleMeta[_role];
    final roleStatus = _roleStatus[_role] ?? _readyMessage;
    final statusKind = _statusKind(roleStatus, _isGenerating && _generationRole == _role);

    return Scaffold(
      backgroundColor: palette.surfaceBg,
      body: Column(
        children: [
          WindowTitleBarBox(
            child: Container(
              height: 36,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Row(
                children: [
                  Expanded(
                    child: MoveWindow(
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: Text('SmoothTalker', style: TextStyle(color: palette.titleColor, fontWeight: FontWeight.w600, fontSize: 12)),
                      ),
                    ),
                  ),
                  const _WindowControls(),
                ],
              ),
            ),
          ),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                return SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: ConstrainedBox(
                    constraints: BoxConstraints(minHeight: constraints.maxHeight > 32 ? constraints.maxHeight - 32 : 0),
                    child: Align(
                      alignment: Alignment.topCenter,
                      child: SizedBox(
                        width: 520,
                child: Container(
                  decoration: BoxDecoration(
                    gradient: palette.surfaceGradient,
                    borderRadius: BorderRadius.circular(12),
                    boxShadow: const [
                      BoxShadow(offset: Offset(0, 8), blurRadius: 10, spreadRadius: -6, color: Color.fromRGBO(0, 0, 0, 0.12)),
                      BoxShadow(offset: Offset(0, 20), blurRadius: 25, spreadRadius: -5, color: Color.fromRGBO(0, 0, 0, 0.12)),
                    ],
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        decoration: BoxDecoration(
                          color: palette.heroBg,
                          borderRadius: const BorderRadius.only(topLeft: Radius.circular(12), topRight: Radius.circular(12)),
                          border: const Border(bottom: BorderSide(color: Color.fromRGBO(15, 23, 42, 0.05))),
                        ),
                        padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Row(
                                  children: [
                                    Container(
                                      width: 32,
                                      height: 32,
                                      decoration: BoxDecoration(
                                        gradient: palette.iconGradient,
                                        borderRadius: BorderRadius.circular(9999),
                                        border: Border.all(color: Colors.white.withOpacity(0.35)),
                                        boxShadow: const [BoxShadow(offset: Offset(0, 6), blurRadius: 14, color: Color.fromRGBO(0, 0, 0, 0.12))],
                                      ),
                                      child: Center(child: Text(_icons.chat, style: const TextStyle(fontSize: 16))),
                                    ),
                                    const SizedBox(width: 12),
                                    Text('SmoothTalker', style: TextStyle(color: palette.titleColor, fontWeight: FontWeight.w700, fontSize: 16, letterSpacing: 0.2)),
                                  ],
                                ),
                                Container(
                                  decoration: BoxDecoration(
                                    color: Colors.white.withOpacity(0.7),
                                    borderRadius: BorderRadius.circular(6),
                                    boxShadow: const [BoxShadow(offset: Offset(0, 1), blurRadius: 2, color: Color.fromRGBO(0, 0, 0, 0.05))],
                                  ),
                                  padding: const EdgeInsets.all(2),
                                  child: Row(
                                    children: [
                                      _RoleChip(
                                        label: 'Crush',
                                        icon: _icons.heart,
                                        active: _role == Role.crush,
                                        onTap: () => _switchRole(Role.crush),
                                        activeBackground: palette.crushChipBg,
                                        activeColor: palette.crushChipText,
                                      ),
                                      const SizedBox(width: 4),
                                      _RoleChip(
                                        label: 'Colleague',
                                        icon: _icons.briefcase,
                                        active: _role == Role.colleague,
                                        onTap: () => _switchRole(Role.colleague),
                                        activeBackground: palette.colleagueChipBg,
                                        activeColor: palette.colleagueChipText,
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                SizedBox(
                                  width: 325,
                                  height: 34,
                                  child: AnimatedSwitcher(
                                    duration: const Duration(milliseconds: 200),
                                    switchInCurve: Curves.easeOut,
                                    switchOutCurve: Curves.easeIn,
                                    child: (_isGenerating && _generationRole == _role)
                                        ? SizedBox(
                                            key: const ValueKey('stop-button'),
                                            width: double.infinity,
                                            height: double.infinity,
                                            child: ElevatedButton(
                                              style: ElevatedButton.styleFrom(
                                                backgroundColor: const Color(0xFFDC2626),
                                                foregroundColor: Colors.white,
                                                elevation: 0,
                                                shadowColor: Colors.transparent,
                                                side: const BorderSide(color: Color(0xFF111827), width: 1),
                                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                                              ).copyWith(
                                                overlayColor: MaterialStateProperty.resolveWith<Color?>(
                                                  (states) {
                                                    if (states.contains(MaterialState.pressed)) return const Color(0xFFB91C1C);
                                                    if (states.contains(MaterialState.hovered)) return const Color(0xFFF87171);
                                                    return null;
                                                  },
                                                ),
                                              ),
                                              onPressed: _cancelGeneration,
                                              child: const Row(
                                                mainAxisAlignment: MainAxisAlignment.center,
                                                children: [
                                                  Icon(Icons.close, size: 16),
                                                  SizedBox(width: 8),
                                                  Text('Stop Generation', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                                                ],
                                              ),
                                            ),
                                          )
                                        : SizedBox(
                                            key: const ValueKey('generate-button'),
                                            width: double.infinity,
                                            height: double.infinity,
                                            child: ElevatedButton(
                                              style: ElevatedButton.styleFrom(
                                                backgroundColor: palette.accent,
                                                foregroundColor: Colors.white,
                                                elevation: _isGenerating ? 0 : 6,
                                                shadowColor: palette.accent.withOpacity(0.35),
                                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                                              ),
                                              onPressed: _isGenerating ? null : _handleGenerate,
                                              child: Row(
                                                mainAxisAlignment: MainAxisAlignment.center,
                                                children: [
                                                  Text(_icons.bolt, style: const TextStyle(fontSize: 14)),
                                                  const SizedBox(width: 10),
                                                  const Text('Generate Replies', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
                                                ],
                                              ),
                                            ),
                                          ),
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 10),
                            TextField(
                              key: ValueKey('thread-${_role.name}'),
                              controller: _threadControllers[_role],
                              style: TextStyle(fontSize: 12, color: palette.titleColor),
                              decoration: InputDecoration(
                                labelText: 'Thread ID',
                                hintText: _role == Role.crush ? 'crush-main' : 'colleague-main',
                                isDense: true,
                                filled: true,
                                fillColor: Colors.white.withOpacity(0.78),
                                border: OutlineInputBorder(
                                  borderRadius: BorderRadius.circular(8),
                                  borderSide: const BorderSide(color: Color.fromRGBO(15, 23, 42, 0.08)),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        color: palette.statusBg,
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        child: Row(
                          children: [
                            _StatusDot(kind: statusKind),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                roleStatus,
                                style: TextStyle(fontSize: 12, color: palette.statusText),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        color: Colors.white,
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
                        constraints: const BoxConstraints(minHeight: 100),
                        child: options.isEmpty
                            ? Center(
                                child: Text(
                                  'Click "Generate Replies" to create responses.',
                                  style: TextStyle(color: palette.mutedText, fontSize: 13),
                                  textAlign: TextAlign.center,
                                ),
                              )
                            : Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  if (meta != null) ...[
                                    Text(
                                      'Model: ${meta['model'] ?? '-'} • Latency: ${meta['latency_ms'] ?? '-'} ms',
                                      style: TextStyle(fontSize: 12, color: palette.mutedText),
                                    ),
                                    const SizedBox(height: 12),
                                  ],
                                  ...options.asMap().entries.map(
                                    (entry) => Padding(
                                      padding: const EdgeInsets.only(bottom: 12),
                                      child: _ReplyCard(
                                        index: entry.key,
                                        text: entry.value,
                                        onCopy: () => _handleCopyOption(entry.value, entry.key),
                                        palette: palette,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                      ),
                      Container(
                        decoration: const BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.only(bottomLeft: Radius.circular(12), bottomRight: Radius.circular(12)),
                        ),
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            _FooterLink(
                              label: 'New Thread',
                              palette: palette,
                              onTap: (_isGenerating && _generationRole == _role) ? null : _startNewThread,
                            ),
                            _FooterLink(
                              label: 'Recent Threads',
                              palette: palette,
                              onTap: (_isGenerating && _generationRole == _role) ? null : _openRecentThreadsSheet,
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  StatusKind _statusKind(String status, bool isActiveGenerating) {
    final lower = status.toLowerCase();
    if (isActiveGenerating) return StatusKind.loading;
    if (lower.contains('error') || lower.contains('fail') || lower.contains('cannot')) return StatusKind.error;
    if (lower.contains('ready') ||
        lower.contains('copied') ||
        lower.contains('option') ||
        lower.contains('started') ||
        lower.contains('switched') ||
        lower.contains('deleted')) {
      return StatusKind.success;
    }
    return StatusKind.neutral;
  }

  String _labelForRole(Role role) => role == Role.colleague ? 'colleague' : 'crush';
}

enum StatusKind { success, loading, error, neutral }

class _StatusDot extends StatelessWidget {
  const _StatusDot({required this.kind});

  final StatusKind kind;

  @override
  Widget build(BuildContext context) {
    Color color;
    switch (kind) {
      case StatusKind.success:
        color = const Color(0xFF22C55E);
        break;
      case StatusKind.loading:
        color = const Color(0xFFF59E0B);
        break;
      case StatusKind.error:
        color = const Color(0xFFEF4444);
        break;
      case StatusKind.neutral:
      default:
        color = const Color(0xFFA3AEC2);
    }
    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      width: 8,
      height: 8,
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(8)),
    );
  }
}

class _RoleChip extends StatelessWidget {
  const _RoleChip({
    required this.label,
    required this.icon,
    required this.active,
    required this.onTap,
    required this.activeBackground,
    required this.activeColor,
  });

  final String label;
  final String icon;
  final bool active;
  final VoidCallback onTap;
  final Color activeBackground;
  final Color activeColor;

  @override
  Widget build(BuildContext context) {
    final backgroundColor = active ? activeBackground : Colors.transparent;
    final hoverColor = active
        ? Color.alphaBlend(Colors.white.withOpacity(0.2), activeBackground)
        : const Color(0xFFF1F5F9);

    return Material(
      color: backgroundColor,
      borderRadius: BorderRadius.circular(4),
      clipBehavior: Clip.hardEdge,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(4),
        hoverColor: hoverColor,
        highlightColor: Colors.transparent,
        splashColor: Colors.transparent,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
          child: Row(
            children: [
              Text(icon, style: const TextStyle(fontSize: 12)),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w500,
                  color: active ? activeColor : const Color(0xFF6B7280),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WindowControls extends StatelessWidget {
  const _WindowControls();

  @override
  Widget build(BuildContext context) {
    final buttonColors = WindowButtonColors(
      iconNormal: const Color(0xFF475569),
      iconMouseOver: const Color(0xFF1E293B),
      iconMouseDown: const Color(0xFF1E293B),
      mouseOver: const Color(0xFFE2E8F0),
      mouseDown: const Color(0xFFCBD5F5),
    );

    final closeColors = WindowButtonColors(
      mouseOver: const Color(0xFFFFCDD2),
      mouseDown: const Color(0xFFEF9A9A),
      iconNormal: const Color(0xFFB91C1C),
      iconMouseOver: const Color(0xFF7F1D1D),
      iconMouseDown: const Color(0xFF7F1D1D),
    );

    return Row(
      children: [
        MinimizeWindowButton(colors: buttonColors),
        CloseWindowButton(colors: closeColors),
      ],
    );
  }
}

class _ReplyCard extends StatelessWidget {
  const _ReplyCard({
    required this.index,
    required this.text,
    required this.onCopy,
    required this.palette,
  });

  final int index;
  final String text;
  final VoidCallback onCopy;
  final _Palette palette;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color.fromRGBO(15, 23, 42, 0.08)),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Option ${index + 1}', style: TextStyle(fontSize: 12, color: palette.mutedText, fontWeight: FontWeight.w600)),
              TextButton(onPressed: onCopy, child: Text('Copy', style: TextStyle(color: palette.accent, fontSize: 12))),
            ],
          ),
          const SizedBox(height: 6),
          Text(text, style: TextStyle(fontSize: 13, color: palette.textPrimary, height: 1.4)),
        ],
      ),
    );
  }
}

class _FooterLink extends StatelessWidget {
  const _FooterLink({required this.label, required this.onTap, required this.palette});

  final String label;
  final VoidCallback? onTap;
  final _Palette palette;

  @override
  Widget build(BuildContext context) {
    final color = onTap == null ? palette.mutedText : palette.accent;
    return TextButton(
      onPressed: onTap,
      child: Text(
        label,
        style: TextStyle(color: color, fontWeight: FontWeight.w600),
      ),
    );
  }
}

class _RecentThreadsSheet extends StatelessWidget {
  const _RecentThreadsSheet({
    required this.palette,
    required this.roleLabel,
    required this.currentThreadId,
    required this.threads,
    required this.errorText,
    required this.onSelect,
    required this.onDelete,
  });

  final _Palette palette;
  final String roleLabel;
  final String currentThreadId;
  final List<_RecentThread> threads;
  final String? errorText;
  final ValueChanged<String> onSelect;
  final ValueChanged<String> onDelete;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Recent Threads',
              style: theme.textTheme.titleMedium?.copyWith(
                color: palette.titleColor,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'Switch or delete saved $roleLabel threads.',
              style: TextStyle(color: palette.mutedText, fontSize: 12),
            ),
            const SizedBox(height: 12),
            if ((errorText ?? '').isNotEmpty)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: const Color(0xFFFEF2F2),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  'Recent threads failed to load.\n$errorText',
                  style: const TextStyle(
                    color: Color(0xFF991B1B),
                    fontSize: 12,
                    height: 1.4,
                  ),
                ),
              )
            else if (threads.isEmpty)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  'No saved threads yet. Generate a reply first or start a new thread.',
                  style: TextStyle(color: palette.mutedText, fontSize: 13),
                ),
              )
            else
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 360),
                child: ListView.separated(
                  shrinkWrap: true,
                  itemCount: threads.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final thread = threads[index];
                    final isCurrent = thread.threadId == currentThreadId;
                    final summary = thread.summary.isEmpty ? 'No summary yet.' : thread.summary;

                    return Material(
                      color: isCurrent ? palette.heroBg : const Color(0xFFF8FAFC),
                      borderRadius: BorderRadius.circular(10),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(10),
                        onTap: () => onSelect(thread.threadId),
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      children: [
                                        Flexible(
                                          child: Text(
                                            thread.threadId,
                                            style: TextStyle(
                                              color: palette.titleColor,
                                              fontWeight: FontWeight.w700,
                                              fontSize: 13,
                                            ),
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                        ),
                                        if (isCurrent) ...[
                                          const SizedBox(width: 8),
                                          Container(
                                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                            decoration: BoxDecoration(
                                              color: Colors.white.withOpacity(0.82),
                                              borderRadius: BorderRadius.circular(999),
                                            ),
                                            child: Text(
                                              'Current',
                                              style: TextStyle(
                                                color: palette.accent,
                                                fontSize: 11,
                                                fontWeight: FontWeight.w700,
                                              ),
                                            ),
                                          ),
                                        ],
                                      ],
                                    ),
                                    const SizedBox(height: 6),
                                    Text(
                                      summary,
                                      maxLines: 2,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        color: palette.textPrimary,
                                        fontSize: 12,
                                        height: 1.35,
                                      ),
                                    ),
                                    const SizedBox(height: 6),
                                    Text(
                                      _formatThreadTimestamp(thread.updatedAt),
                                      style: TextStyle(color: palette.mutedText, fontSize: 11),
                                    ),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: 'Delete thread',
                                onPressed: () => onDelete(thread.threadId),
                                icon: const Icon(Icons.delete_outline),
                                color: const Color(0xFFDC2626),
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _formatThreadTimestamp(DateTime? value) {
    if (value == null) return 'Updated just now';
    return 'Updated ${value.year}-${_twoDigits(value.month)}-${_twoDigits(value.day)} ${_twoDigits(value.hour)}:${_twoDigits(value.minute)}';
  }

  String _twoDigits(int value) => value.toString().padLeft(2, '0');
}

class _Palette {
  const _Palette({
    required this.surfaceBg,
    required this.surfaceGradient,
    required this.heroBg,
    required this.accent,
    required this.titleColor,
    required this.statusBg,
    required this.statusText,
    required this.mutedText,
    required this.textPrimary,
    required this.iconGradient,
    required this.crushChipBg,
    required this.crushChipText,
    required this.colleagueChipBg,
    required this.colleagueChipText,
  });

  final Color surfaceBg;
  final Gradient surfaceGradient;
  final Color heroBg;
  final Color accent;
  final Color titleColor;
  final Color statusBg;
  final Color statusText;
  final Color mutedText;
  final Color textPrimary;
  final Gradient iconGradient;
  final Color crushChipBg;
  final Color crushChipText;
  final Color colleagueChipBg;
  final Color colleagueChipText;

  static const colleague = _Palette(
    surfaceBg: Color(0xFFEFF6FF),
    surfaceGradient: LinearGradient(colors: [Color(0xFFEFF6FF), Color(0xFFF8FAFC)], begin: Alignment.centerLeft, end: Alignment.centerRight),
    heroBg: Color(0xFFDBEAFE),
    accent: Color(0xFF2563EB),
    titleColor: Color(0xFF1D4ED8),
    statusBg: Color(0xFFF3F4F6),
    statusText: Color(0xFF374151),
    mutedText: Color(0xFF6B7280),
    textPrimary: Color(0xFF1F2937),
    iconGradient: LinearGradient(colors: [Color(0xFF2563EB), Color(0xFF60A5FA)], begin: Alignment.topLeft, end: Alignment.bottomRight),
    crushChipBg: Color(0xFFFFE4F1),
    crushChipText: Color(0xFF9D174D),
    colleagueChipBg: Color(0xFFDBEAFE),
    colleagueChipText: Color(0xFF2563EB),
  );

  static const crush = _Palette(
    surfaceBg: Color(0xFFFFE6F4),
    surfaceGradient: LinearGradient(colors: [Color(0xFFFFE6F4), Color(0xFFFFF5FB)], begin: Alignment.centerLeft, end: Alignment.centerRight),
    heroBg: Color(0xFFFFD4EB),
    accent: Color(0xFFDB2777),
    titleColor: Color(0xFF9D174D),
    statusBg: Color(0xFFFFE9F6),
    statusText: Color(0xFF9D174D),
    mutedText: Color(0xFFA9486C),
    textPrimary: Color(0xFF7F1D4F),
    iconGradient: LinearGradient(colors: [Color(0xFFDB2777), Color(0xFFF472B6)], begin: Alignment.topLeft, end: Alignment.bottomRight),
    crushChipBg: Color(0xFFFFE4F1),
    crushChipText: Color(0xFFDB2777),
    colleagueChipBg: Color(0xFFF3F4F6),
    colleagueChipText: Color(0xFF6B7280),
  );
}
