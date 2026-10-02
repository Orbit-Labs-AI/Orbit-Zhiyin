"""cost_time field definitions, owned by this feature family."""

FEATURES = {'cost_time.durations.execution_duration_sum_ms': {'name': 'cost_time.durations.execution_duration_sum_ms',
                                                   'unit': 'ms',
                                                   'rule': 'Sum native/reported durations of known calls; '
                                                           'estimates separate',
                                                   'source': 'Respond execution intervals + explicit '
                                                             'duration reports',
                                                   'denominator': None,
                                                   'type': 'deterministic_derived',
                                                   'missing_semantics': 'null if unsupported; '
                                                                        'coverage/effective_samples/unknown_counts '
                                                                        'describe known subsets',
                                                   'provenance': 'event_uid, call_uid, validation_uid, '
                                                                 'criterion_uid, artifact_revision, '
                                                                 'available_at',
                                                   'path_prefix': 'bottleneck_features'},
 'cost_time.durations.estimated_log_gap_sum_ms': {'name': 'cost_time.durations.estimated_log_gap_sum_ms',
                                                  'unit': 'ms',
                                                  'rule': 'Sum observed event-difference estimates; not '
                                                          'execution or human work duration',
                                                  'source': 'tool_call.duration_source',
                                                  'denominator': None,
                                                  'type': 'proxy',
                                                  'missing_semantics': 'null if unsupported; '
                                                                       'coverage/effective_samples/unknown_counts '
                                                                       'describe known subsets',
                                                  'provenance': 'event_uid, call_uid, validation_uid, '
                                                                'criterion_uid, artifact_revision, '
                                                                'available_at',
                                                  'path_prefix': 'bottleneck_features'}}
