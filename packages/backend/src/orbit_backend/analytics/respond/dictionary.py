"""respond field definitions, owned by this feature family."""

FEATURES = {'respond.retry_links': {'name': 'respond.retry_links',
                         'unit': 'call pair',
                         'rule': 'Prior failure, same task/tool/status scope plus explicit link or matching '
                                 'digest identity; otherwise candidate',
                         'source': 'tool_call',
                         'denominator': None,
                         'type': 'deterministic_derived',
                         'missing_semantics': 'null if unsupported; '
                                              'coverage/effective_samples/unknown_counts describe known '
                                              'subsets',
                         'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                       'artifact_revision, available_at',
                         'path_prefix': 'bottleneck_features'},
 'respond.failure_reasons': {'name': 'respond.failure_reasons',
                             'unit': 'protocol reason',
                             'rule': 'Retain explicit reason and result scope; no stdout inference',
                             'source': 'tool_call.error_class/failure_reason',
                             'denominator': None,
                             'type': 'deterministic_derived',
                             'missing_semantics': 'null if unsupported; '
                                                  'coverage/effective_samples/unknown_counts describe known '
                                                  'subsets',
                             'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                           'artifact_revision, available_at',
                             'path_prefix': 'bottleneck_features'},
 'respond.subagent_relations': {'name': 'respond.subagent_relations',
                                'unit': 'session relation',
                                'rule': 'Explicit parent and spawn/join IDs; fork is separate',
                                'source': 'session.parent_uid + event.attrs',
                                'denominator': None,
                                'type': 'deterministic_derived',
                                'missing_semantics': 'null if unsupported; '
                                                     'coverage/effective_samples/unknown_counts describe '
                                                     'known subsets',
                                'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                              'artifact_revision, available_at',
                                'path_prefix': 'bottleneck_features'},
 'respond.execution_intervals': {'name': 'respond.execution_intervals',
                                 'unit': 'UTC ms interval',
                                 'rule': 'Reliable native endpoints; half-open overlaps only',
                                 'source': 'native execution bounds',
                                 'denominator': None,
                                 'type': 'deterministic_derived',
                                 'missing_semantics': 'null if unsupported; '
                                                      'coverage/effective_samples/unknown_counts describe '
                                                      'known subsets',
                                 'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                               'artifact_revision, available_at',
                                 'path_prefix': 'bottleneck_features'},
 'respond.parallel_intervals': {'name': 'respond.parallel_intervals',
                                'unit': 'UTC ms interval',
                                'rule': 'Reliable native endpoints; half-open overlaps only',
                                'source': 'native execution bounds',
                                'denominator': None,
                                'type': 'deterministic_derived',
                                'missing_semantics': 'null if unsupported; '
                                                     'coverage/effective_samples/unknown_counts describe '
                                                     'known subsets',
                                'provenance': 'event_uid, call_uid, validation_uid, criterion_uid, '
                                              'artifact_revision, available_at',
                                'path_prefix': 'bottleneck_features'}}
