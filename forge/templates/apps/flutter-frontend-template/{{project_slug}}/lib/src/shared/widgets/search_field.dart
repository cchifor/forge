import 'dart:async';

import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';

class SearchField extends StatefulWidget {
  const SearchField({
    required this.onChanged,
    this.hintText = 'Search...',
    this.controller,
    this.debounceDuration = const Duration(milliseconds: DesignTokens.durationDebounce),
    super.key,
  });

  final ValueChanged<String> onChanged;
  final String hintText;
  final TextEditingController? controller;
  final Duration debounceDuration;

  @override
  State<SearchField> createState() => _SearchFieldState();
}

class _SearchFieldState extends State<SearchField> {
  late final TextEditingController _controller;
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _controller = widget.controller ?? TextEditingController();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    if (widget.controller == null) _controller.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(widget.debounceDuration, () {
      widget.onChanged(value);
    });
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _controller,
      onChanged: _onChanged,
      decoration: InputDecoration(
        hintText: widget.hintText,
        prefixIcon: const Icon(Icons.search),
        suffixIcon: ListenableBuilder(
          listenable: _controller,
          builder: (context, _) {
            if (_controller.text.isEmpty) return const SizedBox.shrink();
            return IconButton(
              icon: const Icon(Icons.clear),
              onPressed: () {
                _controller.clear();
                widget.onChanged('');
              },
            );
          },
        ),
        border: const OutlineInputBorder(),
        isDense: true,
      ),
    );
  }
}
