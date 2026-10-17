import { useQuery } from "@tanstack/react-query";

import { fetchProjects } from "../api";

/** The projects the user may read; one cache entry shared by every page. */
export const useProjects = () => useQuery({ queryKey: ["projects"], queryFn: fetchProjects });
