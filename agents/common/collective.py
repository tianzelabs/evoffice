"""Stateless shared-REPL handle; credentials and HTTP clients are never persisted."""
from agents.common.office_client import Office
from agents.common.experience import compact_experience


class CollectiveMemory:
    def _call(self,method,*args,**kwargs):
        office=Office()
        try:
            return getattr(office,method)(*args,**kwargs)
        finally:
            office.http.close()

    def experience(self,detail=False):
        result=self._call('get','/research/experience')
        return result if detail else compact_experience(result)

    def knowledge(self,topic=None,limit=20):
        return self._call('get','/knowledge',**({'topic':topic} if topic else {}),limit=limit)

    def remember(self,entry):
        return self._call('post','/knowledge',entry)
