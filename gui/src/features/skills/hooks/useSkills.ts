import { useQuery } from '@tanstack/react-query';

import { fetchSkills } from '../api/skillsApi';

const SKILLS_KEY = ['skills', 'list'] as const;

export function useSkills() {
  return useQuery({
    queryKey: SKILLS_KEY,
    queryFn: fetchSkills,
    refetchInterval: 15000,
  });
}
