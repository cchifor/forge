"""Dart code templates for dynamic feature generation.

All templates use Python str.format() with named placeholders.
Literal Dart curly braces are escaped as {{ and }}.
"""


def make_feature_context(plural: str, package_name: str) -> dict:
    """Derive all naming variants from the plural feature name."""
    singular = (
        plural.rstrip("s")
        if plural.endswith("s") and len(plural) > 1
        else plural
    )
    return {
        "pkg": package_name,
        "plural": plural,                          # items
        "singular": singular,                       # item
        "Plural": plural[0].upper() + plural[1:],  # Items
        "Singular": singular[0].upper() + singular[1:],  # Item
    }


# ═══════════════════════════════════════════════════════════════════
# FEATURE FILE TEMPLATES (10 per feature)
# ═══════════════════════════════════════════════════════════════════

ROUTES_TEMPLATE = """\
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../routing/route_names.dart';
import 'presentation/{plural}_list_page.dart';
import 'presentation/{singular}_detail_page.dart';
import 'presentation/{singular}_create_page.dart';

abstract final class {Plural}Routes {{
  static List<RouteBase> get routes => [
        GoRoute(
          path: '/{plural}',
          name: RouteNames.{plural},
          builder: (context, state) => const {Plural}ListPage(),
          routes: [
            GoRoute(
              path: 'new',
              name: RouteNames.{singular}Create,
              pageBuilder: (context, state) => _slideUpPage(
                key: state.pageKey,
                child: const {Singular}CreatePage(),
              ),
            ),
            GoRoute(
              path: ':id',
              name: RouteNames.{singular}Detail,
              pageBuilder: (context, state) {{
                final id = state.pathParameters['id']!;
                return _slideUpPage(
                  key: state.pageKey,
                  child: {Singular}DetailPage({singular}Id: id),
                );
              }},
            ),
          ],
        ),
      ];

  static CustomTransitionPage<void> _slideUpPage({{
    required LocalKey key,
    required Widget child,
  }}) {{
    return CustomTransitionPage(
      key: key,
      child: child,
      transitionDuration: const Duration(milliseconds: 250),
      reverseTransitionDuration: const Duration(milliseconds: 200),
      transitionsBuilder: (context, animation, secondaryAnimation, child) {{
        final offsetTween = Tween(
          begin: const Offset(0, 0.04),
          end: Offset.zero,
        ).chain(CurveTween(curve: Curves.easeOutCubic));
        final fadeTween = Tween(begin: 0.0, end: 1.0)
            .chain(CurveTween(curve: Curves.easeOut));
        return FadeTransition(
          opacity: animation.drive(fadeTween),
          child: SlideTransition(
            position: animation.drive(offsetTween),
            child: child,
          ),
        );
      }},
    );
  }}
}}
"""

REPOSITORY_TEMPLATE = """\
import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../api/client/dio_client.dart';

part '{plural}_repository.g.dart';

class {Plural}Repository {{
  {Plural}Repository({{required Dio dio}}) : _dio = dio;

  final Dio _dio;

  Future<Map<String, dynamic>> list{Plural}({{
    int skip = 0,
    int limit = 50,
  }}) async {{
    final response = await _dio.get(
      '/{plural}',
      queryParameters: {{'skip': skip, 'limit': limit}},
    );
    return response.data as Map<String, dynamic>;
  }}

  Future<Map<String, dynamic>> get{Singular}(String id) async {{
    final response = await _dio.get('/{plural}/$id');
    return response.data as Map<String, dynamic>;
  }}

  Future<Map<String, dynamic>> create{Singular}(Map<String, dynamic> data) async {{
    final response = await _dio.post('/{plural}', data: data);
    return response.data as Map<String, dynamic>;
  }}

  Future<Map<String, dynamic>> update{Singular}(String id, Map<String, dynamic> data) async {{
    final response = await _dio.patch('/{plural}/$id', data: data);
    return response.data as Map<String, dynamic>;
  }}

  Future<void> delete{Singular}(String id) async {{
    await _dio.delete('/{plural}/$id');
  }}
}}

@riverpod
{Plural}Repository {plural}Repository(Ref ref) {{
  return {Plural}Repository(dio: ref.watch(dioProvider));
}}
"""

QUERY_PARAMS_TEMPLATE = """\
import 'package:freezed_annotation/freezed_annotation.dart';

part '{plural}_query_params.freezed.dart';

@freezed
abstract class {Plural}QueryParams with _${Plural}QueryParams {{
  const factory {Plural}QueryParams({{
    @Default(0) int skip,
    @Default(50) int limit,
    String? search,
  }}) = _{Plural}QueryParams;

  const {Plural}QueryParams._();

  {Plural}QueryParams nextPage() => copyWith(skip: skip + limit);
  {Plural}QueryParams resetPagination() => copyWith(skip: 0);
}}
"""

CONTROLLER_TEMPLATE = """\
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../data/{plural}_repository.dart';
import '../domain/{plural}_query_params.dart';

part '{plural}_controller.g.dart';

@riverpod
class {Plural}QueryParamsNotifier extends _${Plural}QueryParamsNotifier {{
  @override
  {Plural}QueryParams build() => const {Plural}QueryParams();

  void setSearch(String? search) {{
    state = state.copyWith(
      search: search?.isEmpty == true ? null : search,
      skip: 0,
    );
  }}

  void nextPage() {{
    state = state.nextPage();
  }}

  void reset() {{
    state = const {Plural}QueryParams();
  }}
}}

@riverpod
Future<Map<String, dynamic>> {plural}List(Ref ref) async {{
  final params = ref.watch({plural}QueryParamsProvider);
  final repo = ref.watch({plural}RepositoryProvider);
  return repo.list{Plural}(
    skip: params.skip,
    limit: params.limit,
  );
}}

@riverpod
class {Plural}Controller extends _${Plural}Controller {{
  @override
  FutureOr<void> build() {{}}

  Future<bool> create{Singular}(Map<String, dynamic> data) async {{
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {{
      final repo = ref.read({plural}RepositoryProvider);
      await repo.create{Singular}(data);
    }});
    if (!state.hasError) {{
      ref.invalidate({plural}ListProvider);
    }}
    return !state.hasError;
  }}

  Future<bool> update{Singular}(String id, Map<String, dynamic> data) async {{
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {{
      final repo = ref.read({plural}RepositoryProvider);
      await repo.update{Singular}(id, data);
    }});
    if (!state.hasError) {{
      ref.invalidate({plural}ListProvider);
      ref.invalidate({singular}DetailProvider(id));
    }}
    return !state.hasError;
  }}

  Future<bool> delete{Singular}(String id) async {{
    state = const AsyncLoading();
    state = await AsyncValue.guard(() async {{
      final repo = ref.read({plural}RepositoryProvider);
      await repo.delete{Singular}(id);
    }});
    if (!state.hasError) {{
      ref.invalidate({plural}ListProvider);
    }}
    return !state.hasError;
  }}
}}

@riverpod
Future<Map<String, dynamic>> {singular}Detail(Ref ref, String id) async {{
  final repo = ref.watch({plural}RepositoryProvider);
  return repo.get{Singular}(id);
}}
"""

LIST_PAGE_TEMPLATE = """\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../routing/route_names.dart';
import '../../../shared/feedback/feedback_extensions.dart';
import '../../../shared/widgets/async_value_widget.dart';
import '../../../shared/widgets/empty_state_widget.dart';
import '../../../shared/widgets/search_field.dart';
import '../../../theme/design_tokens.dart';
import '{plural}_controller.dart';
import 'widgets/{singular}_card.dart';

class {Plural}ListPage extends ConsumerWidget {{
  const {Plural}ListPage({{super.key}});

  @override
  Widget build(BuildContext context, WidgetRef ref) {{
    final dataAsync = ref.watch({plural}ListProvider);

    ref.listen({plural}ControllerProvider, (prev, next) {{
      handleAsyncFeedback(context, prev, next);
    }});

    return Scaffold(
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              DesignTokens.p16, DesignTokens.p16, DesignTokens.p16, DesignTokens.p8,
            ),
            child: SearchField(
              hintText: 'Search {plural}...',
              onChanged: (value) {{
                ref.read({plural}QueryParamsProvider.notifier).setSearch(value);
              }},
            ),
          ),
          const SizedBox(height: DesignTokens.p8),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async => ref.invalidate({plural}ListProvider),
              child: AsyncValueWidget(
                value: dataAsync,
                data: (data) {{
                  final items = (data['items'] as List?) ?? [];
                  if (items.isEmpty) {{
                    return const EmptyStateWidget(
                      message: 'No {plural} found',
                      icon: Icons.inventory_2_outlined,
                    );
                  }}
                  return ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: DesignTokens.p16),
                    itemCount: items.length,
                    itemBuilder: (context, index) {{
                      final item = items[index] as Map<String, dynamic>;
                      return {Singular}Card(
                        data: item,
                        onTap: () => context.goNamed(
                          RouteNames.{singular}Detail,
                          pathParameters: {{'id': item['id'].toString()}},
                        ),
                      );
                    }},
                  );
                }},
              ),
            ),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.goNamed(RouteNames.{singular}Create),
        icon: const Icon(Icons.add),
        label: const Text('New {Singular}'),
      ),
    );
  }}
}}
"""

DETAIL_PAGE_TEMPLATE = """\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../shared/feedback/feedback_extensions.dart';
import '../../../shared/widgets/async_value_widget.dart';
import '../../../shared/widgets/confirm_dialog.dart';
import '../../../theme/design_tokens.dart';
import '{plural}_controller.dart';

class {Singular}DetailPage extends ConsumerWidget {{
  const {Singular}DetailPage({{required this.{singular}Id, super.key}});

  final String {singular}Id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {{
    final dataAsync = ref.watch({singular}DetailProvider({singular}Id));

    ref.listen({plural}ControllerProvider, (prev, next) {{
      handleAsyncFeedback(context, prev, next);
    }});

    return Scaffold(
      appBar: AppBar(
        title: const Text('{Singular} Details'),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline),
            tooltip: 'Delete',
            onPressed: () async {{
              final confirmed = await showConfirmDialog(
                context: context,
                title: 'Delete {Singular}',
                content: 'Are you sure? This cannot be undone.',
                confirmText: 'Delete',
                isDestructive: true,
              );
              if (confirmed && context.mounted) {{
                final success = await ref
                    .read({plural}ControllerProvider.notifier)
                    .delete{Singular}({singular}Id);
                if (success && context.mounted) context.pop();
              }}
            }},
          ),
        ],
      ),
      body: AsyncValueWidget(
        value: dataAsync,
        data: (data) {{
          return ListView(
            padding: const EdgeInsets.all(DesignTokens.p16),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(DesignTokens.p16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        data['name']?.toString() ?? 'Untitled',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      if (data['description'] != null) ...[
                        const SizedBox(height: DesignTokens.p8),
                        Text(data['description'].toString()),
                      ],
                      const SizedBox(height: DesignTokens.p16),
                      Text(
                        'ID: ${{data['id']}}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
        }},
      ),
    );
  }}
}}
"""

CREATE_PAGE_TEMPLATE = """\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../shared/feedback/feedback_extensions.dart';
import '{plural}_controller.dart';
import 'widgets/{singular}_form.dart';

class {Singular}CreatePage extends ConsumerWidget {{
  const {Singular}CreatePage({{super.key}});

  @override
  Widget build(BuildContext context, WidgetRef ref) {{
    final controllerState = ref.watch({plural}ControllerProvider);

    ref.listen({plural}ControllerProvider, (prev, next) {{
      handleAsyncFeedback(context, prev, next, successMessage: '{Singular} created');
    }});

    return Scaffold(
      appBar: AppBar(
        title: const Text('Create {Singular}'),
        leading: const BackButton(),
      ),
      body: {Singular}Form(
        isLoading: controllerState.isLoading,
        onSubmit: (data) async {{
          final success = await ref
              .read({plural}ControllerProvider.notifier)
              .create{Singular}(data);
          if (success && context.mounted) context.pop();
        }},
      ),
    );
  }}
}}
"""

CARD_WIDGET_TEMPLATE = """\
import 'package:flutter/material.dart';

import '../../../../theme/design_tokens.dart';

class {Singular}Card extends StatelessWidget {{
  const {Singular}Card({{
    required this.data,
    required this.onTap,
    super.key,
  }});

  final Map<String, dynamic> data;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {{
    final theme = Theme.of(context);

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(DesignTokens.p16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                data['name']?.toString() ?? 'Untitled',
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
              if (data['description'] != null) ...[
                const SizedBox(height: DesignTokens.p8),
                Text(
                  data['description'].toString(),
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }}
}}
"""

FORM_WIDGET_TEMPLATE = """\
import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';
import 'package:hooks_riverpod/hooks_riverpod.dart';

import '../../../../theme/design_tokens.dart';

class {Singular}Form extends HookConsumerWidget {{
  const {Singular}Form({{
    required this.onSubmit,
    this.isLoading = false,
    super.key,
  }});

  final Future<void> Function(Map<String, dynamic> data) onSubmit;
  final bool isLoading;

  @override
  Widget build(BuildContext context, WidgetRef ref) {{
    final formKey = useMemoized(GlobalKey<FormState>.new);
    final nameController = useTextEditingController();
    final descriptionController = useTextEditingController();

    return Form(
      key: formKey,
      child: ListView(
        padding: const EdgeInsets.all(DesignTokens.p16),
        children: [
          TextFormField(
            controller: nameController,
            decoration: const InputDecoration(
              labelText: 'Name',
              hintText: 'Enter {singular} name',
            ),
            validator: (value) {{
              if (value == null || value.trim().isEmpty) return 'Name is required';
              return null;
            }},
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: DesignTokens.p16),
          TextFormField(
            controller: descriptionController,
            decoration: const InputDecoration(
              labelText: 'Description',
              hintText: 'Enter description',
            ),
            maxLines: 3,
          ),
          const SizedBox(height: DesignTokens.p24),
          FilledButton.icon(
            onPressed: isLoading
                ? null
                : () {{
                    if (formKey.currentState!.validate()) {{
                      onSubmit({{
                        'name': nameController.text.trim(),
                        'description': descriptionController.text.trim().isEmpty
                            ? null
                            : descriptionController.text.trim(),
                      }});
                    }}
                  }},
            icon: isLoading
                ? const SizedBox(
                    width: 18, height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.save),
            label: Text(isLoading ? 'Saving...' : 'Create {Singular}'),
          ),
        ],
      ),
    );
  }}
}}
"""

# ═══════════════════════════════════════════════════════════════════
# TEST TEMPLATES
# ═══════════════════════════════════════════════════════════════════

FIXTURE_TEMPLATE = """\
// Test fixtures for {plural} feature.
final test{Singular}Json = {{
  'id': 'test-{singular}-id',
  'name': 'Test {Singular}',
  'description': 'A test {singular} for unit tests',
}};
"""

REPO_TEST_TEMPLATE = """\
import 'package:flutter_test/flutter_test.dart';

void main() {{
  group('{Plural}Repository', () {{
    test('placeholder test', () {{
      expect(true, isTrue);
    }});
  }});
}}
"""

# ═══════════════════════════════════════════════════════════════════
# HUB INJECTION SNIPPETS
# ═══════════════════════════════════════════════════════════════════

HUB_ROUTE_NAMES = """\
  static const String {plural} = '{plural}';
  static const String {singular}Create = '{singular}Create';
  static const String {singular}Detail = '{singular}Detail';"""

HUB_ROUTER_IMPORT = """\
import '../features/{plural}/{plural}_routes.dart';"""

HUB_ROUTER_BRANCH = """\
          StatefulShellBranch(routes: {Plural}Routes.routes),"""

HUB_NAV_DESTINATION = """\
  (
    icon: Icons.inventory_2_outlined,
    selectedIcon: Icons.inventory_2,
    label: '{Plural}',
    section: NavSection.primary,
  ),"""

HUB_BREADCRUMB = """\
    '{plural}': '{Plural}',"""

HUB_BUILD_YAML_FREEZED = """\
            - lib/src/features/{plural}/domain/*.dart"""

HUB_BUILD_YAML_RIVERPOD = """\
            - lib/src/features/{plural}/data/*.dart
            - lib/src/features/{plural}/presentation/*_controller.dart"""

IMPORT_LINT_RULE = """\
  {plural}_feature_isolation:
    search_file_path_reg_exp: ".*/features/{plural}/.*\\\\.dart"
    not_allow_import_reg_exps:
{not_allow_lines}
    ignore_import_reg_exps: []"""
