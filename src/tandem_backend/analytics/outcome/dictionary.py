"""outcome field definitions, owned by this feature family."""

FEATURES = {'outcome.validation_runs': {'name': 'outcome.validation_runs',
                             'unit': 'validation execution',
                             'rule': 'Explicit executed check metadata or complete direct checking command '
                                     'with command-level return',
                             'source': 'tool_call.validation + protocol result',
                             'denominator': None,
                             'type': 'deterministic_derived',
                             'missing_semantics': 'null if unsupported; '
                                                  'coverage/effective_samples/unknown_counts describe known '
                                                  'subsets',
                             'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                           'artifact_revision, available_at',
                             'path_prefix': 'bottleneck_features'},
 'outcome.acceptance_results': {'name': 'outcome.acceptance_results',
                                'unit': 'criterion',
                                'rule': 'Match explicit criterion, task, session tree, kind, object revision '
                                        'and exact coverage',
                                'source': 'attrs.acceptance + validation evidence',
                                'denominator': None,
                                'type': 'deterministic_derived',
                                'missing_semantics': 'null if unsupported; '
                                                     'coverage/effective_samples/unknown_counts describe '
                                                     'known subsets',
                                'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                              'artifact_revision, available_at',
                                'path_prefix': 'bottleneck_features'},
 'outcome.task_success': {'name': 'outcome.task_success',
                          'unit': 'nullable boolean',
                          'rule': 'Only a single explicit complete acceptance set can establish scoped '
                                  'success; absent criteria remain null',
                          'source': 'outcome.acceptance_results',
                          'denominator': None,
                          'type': 'deterministic_derived',
                          'missing_semantics': 'null if unsupported; '
                                               'coverage/effective_samples/unknown_counts describe known '
                                               'subsets',
                          'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                        'artifact_revision, available_at',
                          'path_prefix': 'bottleneck_features'}}
